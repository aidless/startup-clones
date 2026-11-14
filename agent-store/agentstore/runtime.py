"""执行器：权限闸在执行前拦，计量只在成功后发生（失败不收费）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .registry import Registry, RegistryError


@dataclass
class Execution:
    request_id: str
    agent_id: str
    version: str
    buyer: str
    ok: bool
    output: str = ""
    error: str = ""
    charged_cents: int = 0
    duplicate: bool = False      # 同一 (buyer, request_id) 的重放：不再执行、不再计费
    audit: list[dict] = field(default_factory=list)

    def render(self) -> str:
        tag = "OK " if self.ok else "ERR"
        money = f" ${self.charged_cents / 100:.2f}" if self.charged_cents else " 免费"
        head = f"[{tag}] {self.agent_id}@{self.version}{money}"
        return f"{head}\n  {self.output or self.error}"


def _audit(exec_obj: Execution, step: str, **kw) -> None:
    exec_obj.audit.append({"step": step, **kw})


class Runtime:
    """极简执行器：不做真沙箱，但把「该拦的地方拦在哪一步」写清楚。"""

    def __init__(self, registry: Registry, ledger=None):
        self.registry = registry
        self.ledger = ledger
        # 已执行的请求结果：重投直接回放，不重跑 handler。
        # 这只是**进程内缓存**；权威在 ledger（usage 表按 (buyer, request_id) 记执行结果）。
        # 只靠进程内字典时，重启 / 换 worker / 多副本下同一 request_id 会重跑 handler。
        self._done: dict[tuple[str, str], Execution] = {}

    def execute(self, buyer: str, agent_id: str,
                handler: Callable[[str], tuple[str, int]],
                request_id: str, needs: tuple[str, ...] = (),
                tokens: int = 0) -> Execution:
        # 幂等判断先于一切：已落库的请求直接回放（不验权限、不再执行、不再计费）。
        # 否则「重投」在重启后会被当成新请求，handler 的副作用（发邮件、动账）再发生一次。
        seen = self._done.get((buyer, request_id))
        if seen is None and self.ledger is not None:
            row = self.ledger.replay(buyer, request_id)
            if row is not None:
                seen = Execution(request_id, row.agent_id, row.version, buyer, row.ok,
                                 output=row.output, error=row.error,
                                 charged_cents=row.cents, duplicate=True)
                self._done[(buyer, request_id)] = seen
        if seen is not None:
            replay = Execution(request_id, agent_id, seen.version, buyer, seen.ok,
                               output=seen.output, error=seen.error,
                               charged_cents=seen.charged_cents, duplicate=True)
            _audit(replay, "gate", result="duplicate", dedup=True)
            return replay

        try:
            v = self.registry.get(agent_id, self.registry.granted_version(buyer, agent_id))
        except RegistryError as exc:
            return Execution(request_id, agent_id, "-", buyer, False, error=f"未安装: {exc}")

        # 先验安装凭据，再验权限，最后才执行 —— 顺序不能换，否则会先消耗模型调用

        ex = Execution(request_id, agent_id, v.version, buyer, False)
        _audit(ex, "resolve", version=v.version, status=v.status)

        if v.status != "published":
            ex.error = f"版本已下架: {v.version}"
            _audit(ex, "gate", result="yanked")
            return ex

        granted = set(self.registry.granted(buyer, agent_id))
        missing = [p for p in needs if p not in granted]
        if missing:
            ex.error = f"permission_denied: {', '.join(missing)}"
            _audit(ex, "gate", result="denied", missing=missing)
            return ex      # 明确不写计量：被拦掉的请求不该出现账单
        _audit(ex, "gate", result="allowed", needs=list(needs))

        try:
            output, units = handler(ex.request_id)
        except Exception as exc:               # noqa: BLE001 —— 执行失败统一折算成不收费
            ex.error = f"handler_error: {exc}"
            _audit(ex, "execute", result="error")
            return ex

        ex.ok, ex.output = True, output
        _audit(ex, "execute", result="ok", units=units)

        self._done[(buyer, request_id)] = ex

        if self.ledger is not None:
            try:
                record = self.ledger.record(
                    buyer, agent_id, v.version, ex.request_id,
                    units=units if v.manifest.pricing.kind != "per_token" else max(units, tokens),
                    ok=ex.ok, output=ex.output, error=ex.error)
            except KeyError as exc:
                # 计量器不认识这个清单（没 register）→ 原实现让 KeyError 穿透到调用方，
                # 此时 handler 已经跑完、模型调用已经花掉，调用方却拿到裸 KeyError。
                # 结果保留、不收费、把原因写进 error 让人能修。
                ex.error = f"meter_unregistered: {exc}"
                _audit(ex, "meter", result="unregistered")
                return ex
            ex.charged_cents = record.cents
            _audit(ex, "meter", cents=record.cents, dedup=record.duplicate)
        return ex


# Registry 上的便捷方法（保持 registry 本身不含运行时概念）
def _granted_version(self: Registry, buyer: str, agent_id: str) -> str:
    row = self.conn.execute("SELECT version FROM installs WHERE buyer=? AND agent_id=?",
                            (buyer, agent_id)).fetchone()
    if not row:
        raise RegistryError(f"{buyer} 未安装 {agent_id}")
    return row[0]


Registry.granted_version = _granted_version  # type: ignore[attr-defined]
