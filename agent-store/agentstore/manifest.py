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
        if self.kind != "subscription" and self.cents_per_unit <= 0:
            raise ManifestError("按量计费必须给出正价格（美分）")
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

    def validate(self) -> None:
        if not self.agent_id or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", self.agent_id):
            raise ManifestError(f"agent_id 不合法: {self.agent_id!r}")
        if not SEMVER_RE.match(self.version):
            raise ManifestError(f"version 必须是 x.y.z: {self.version!r}")
        if not self.entrypoint:
            raise ManifestError("缺少 entrypoint")
        unknown = [p for p in self.permissions if p not in KNOWN_PERMISSIONS]
        if unknown:
            raise ManifestError(f"未知权限: {unknown}")
        self.pricing.validate()

    # ---- 不可变性 ------------------------------------------------
    def canonical(self) -> dict:
        d = asdict(self)
        d["permissions"] = sorted(self.permissions)
        return d

    def digest(self) -> str:
        """内容哈希：上架后这个值一变就说明版本被改过（版本号不可覆盖）。"""
        payload = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()


def parse_version(v: str) -> tuple[int, int, int]:
    if not SEMVER_RE.match(v):
        raise ManifestError(f"version 必须是 x.y.z: {v!r}")
    return tuple(int(x) for x in v.split("."))  # type: ignore[return-value]


def bump(version: str, part: str = "patch") -> str:
    major, minor, patch = parse_version(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ManifestError(f"未知升级位: {part}")
