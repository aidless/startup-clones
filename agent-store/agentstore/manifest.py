"""清单模型：一个 agent 上架必须先说清楚「它能碰什么、怎么收费」。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# 权限是白名单式的，未知权限一律拒绝（新增权限必须改这里，不能靠字符串自由发挥）
KNOWN_PERMISSIONS = {
    "net.outbound",      # 允许出网
    "fs.read",           # 读工作目录
    "fs.write",          # 写工作目录
    "secrets.read",      # 读调用方注入的凭据
    "email.send",
    "payment.charge",
}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Pricing:
    """计费方式三选一。价格单位：美分（整数），避免浮点误差。"""

    kind: str                 # per_call | per_token | subscription
    cents_per_unit: int = 0   # per_call: 每次调用；per_token: 每 1k token；subscription: 每周期
    period: str = "month"     # subscription 用

    def validate(self) -> None:
        if self.kind not in {"per_call", "per_token", "subscription"}:
            raise ManifestError(f"未知计费方式: {self.kind}")
        if self.cents_per_unit <= 0:
            # 订阅也必须为正：负价等于平台倒贴（可被刷成负数账单），
            # 0 价则「走计费通道但不收钱」，两种都该在入市时拒掉。
            raise ManifestError("价格必须为正（美分）"
                                + ("，按量计费" if self.kind != "subscription" else "，订阅同样如此"))
        if self.kind == "subscription" and self.period not in {"month", "year"}:
            raise ManifestError("订阅周期只能是 month/year")


@dataclass(frozen=True)
class AgentManifest:
    agent_id: str
    version: str
    name: str
    entrypoint: str
    pricing: Pricing
    permissions: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    # 调用期实际会要求的权限，必须 ⊆ permissions。
    # 放进清单而不是只写在文档里：否则「装完之后它要拿什么权限」可以绕过 digest 被改。
    needs: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.agent_id or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", self.agent_id):
            raise ManifestError(f"agent_id 不合法: {self.agent_id!r}")
        if not SEMVER_RE.match(self.version):
            raise ManifestError(f"version 必须是 x.y.z: {self.version!r}")
        if not self.entrypoint:
            raise ManifestError("缺少 entrypoint")
        unknown = [p for p in tuple(self.permissions) + tuple(self.needs)
                   if p not in KNOWN_PERMISSIONS]
        if unknown:
            raise ManifestError(f"未知权限: {unknown}")
        outside = [p for p in self.needs if p not in self.permissions]
        if outside:
            raise ManifestError(f"needs 里有清单未声明的权限: {outside}（needs 必须 ⊆ permissions）")
        self.pricing.validate()

    # ---- 不可变性 ------------------------------------------------
    def canonical(self) -> dict:
        d = asdict(self)
        d["permissions"] = sorted(self.permissions)
        d["needs"] = sorted(self.needs)
        return d

    def digest(self) -> str:
        """内容哈希：上架后这个值一变就说明版本被改过（版本号不可覆盖）。"""
        payload = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()


def parse_version(v: str) -> tuple[int, int, int]:
    if not SEMVER_RE.match(v):
        raise ManifestError(f"version 必须是 x.y.z: {v!r}")
    return tuple(int(x) for x in v.split("."))  # type: ignore[return-value]


def from_dict(data: dict) -> AgentManifest:
    """把 agent.json 那种扁平字典变成清单（运行期加载入口）。

    接受两个人类友好别名：`id` → agent_id、`price` → pricing。
    任何字段问题一律归到 ManifestError，不让 KeyError/TypeError 漏给调用方。
    """
    if not isinstance(data, dict):
        raise ManifestError("清单必须是 JSON 对象")
    d = dict(data)
    if "id" in d:
        d.setdefault("agent_id", d.pop("id"))
    if "price" in d:
        d.setdefault("pricing", d.pop("price"))
    pricing = d.get("pricing")
    if isinstance(pricing, dict):
        try:
            d["pricing"] = Pricing(**pricing)
        except TypeError as exc:
            raise ManifestError(f"pricing 字段不认识: {exc}") from exc
    d["permissions"] = tuple(d.get("permissions") or ())
    d["needs"] = tuple(d.get("needs") or ())
    d.setdefault("entrypoint", "handler:run")
    try:
        manifest = AgentManifest(**d)
    except TypeError as exc:
        raise ManifestError(f"清单字段不认识: {exc}") from exc
    manifest.validate()
    return manifest


def load_manifest(path) -> AgentManifest:
    """读一份 agent.json 并校验，返回清单对象。"""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise ManifestError(f"读不到清单 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"清单不是合法 JSON {path}: {exc}") from exc
    return from_dict(data)


def bump(version: str, part: str = "patch") -> str:
    major, minor, patch = parse_version(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ManifestError(f"未知升级位: {part}")
