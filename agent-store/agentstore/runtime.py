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

    def execute(self, buyer: str, agent_id: str,
                handler: Callable[[str], tuple[str, int]],
                request_id: str, needs: tuple[str, ...] = (),
                tokens: int = 0) -> Execution:
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

        if self.ledger is not None:
            record = self.ledger.record(buyer, agent_id, v.version, ex.request_id,
                                        units=units if v.manifest.pricing.kind != "per_token" else max(units, tokens))
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
