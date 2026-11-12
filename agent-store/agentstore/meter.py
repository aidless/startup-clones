"""计量与账单：价格由清单决定，分成由平台决定，第二次相同的 request_id 不重复计费。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from .manifest import AgentManifest

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    request_id TEXT PRIMARY KEY,     -- 幂等键：渠道重投/客户端重试都撞这里
    buyer      TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    version    TEXT NOT NULL,
    units      INTEGER NOT NULL,
    cents      INTEGER NOT NULL,
    ts         TEXT NOT NULL
);
"""

CNY = Decimal("0.01")


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


@dataclass
class UsageRecord:
    request_id: str
    buyer: str
    agent_id: str
    version: str
    units: int
    cents: int
    duplicate: bool = False


@dataclass
class Line:
    agent_id: str
    developer: str
    calls: int
    units: int
    gross_cents: int
    platform_cents: int
    developer_cents: int


@dataclass
class Statement:
    buyer: str
    lines: list[Line] = field(default_factory=list)

    @property
    def gross_cents(self) -> int:
        return sum(l.gross_cents for l in self.lines)

    def to_markdown(self, fee_pct: int) -> str:
        rows = "\n".join(
            f"| {l.agent_id} | {l.developer} | {l.calls} | {l.units} | {_money(l.gross_cents)} "
            f"| {_money(l.platform_cents)} | {_money(l.developer_cents)} |" for l in self.lines)
        return (
            f"# 账单 · {self.buyer}\n\n"
            "| agent | 开发者 | 调用 | 计量单位 | 应付 | 平台分成 | 开发者应得 |\n"
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |\n"
            f"{rows}\n\n合计应付 **{_money(self.gross_cents)}**（平台抽成 {fee_pct}%）\n"
        )


class Ledger:
    def __init__(self, db_path: str = ":memory:", now: str = "2026-11-12T00:00:00Z"):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self._now = now
        self._manifests: dict[tuple[str, str], AgentManifest] = {}

    def register(self, manifest: AgentManifest) -> None:
        """计量需要清单里的价格；真实系统从 registry 读，这里显式注入便于测试。"""
        self._manifests[(manifest.agent_id, manifest.version)] = manifest

    def price(self, agent_id: str, version: str, units: int) -> int:
        m = self._manifests.get((agent_id, version))
        if m is None:
            raise KeyError(f"未注册清单: {agent_id}@{version}")
        p = m.pricing
        if p.kind == "per_call":
            return p.cents_per_unit
        if p.kind == "per_token":
            # 每 1k token 计价，向上取整到 1k
            thousands = max(1, -(-units // 1000))
            return p.cents_per_unit * thousands
        return p.cents_per_unit          # subscription：按周期一次性

    def record(self, buyer: str, agent_id: str, version: str,
               request_id: str, units: int) -> UsageRecord:
        row = self.conn.execute("SELECT cents FROM usage WHERE request_id=?", (request_id,)).fetchone()
        if row:
            return UsageRecord(request_id, buyer, agent_id, version, units, row[0], duplicate=True)
        cents = self.price(agent_id, version, units)
        self.conn.execute(
            "INSERT INTO usage(request_id,buyer,agent_id,version,units,cents,ts) VALUES(?,?,?,?,?,?,?)",
            (request_id, buyer, agent_id, version, units, cents, self._now))
        self.conn.commit()
        return UsageRecord(request_id, buyer, agent_id, version, units, cents)

    def statement(self, buyer: str, developers: dict[str, str],
                  fee_pct: int = 20) -> Statement:
        rows = self.conn.execute(
            "SELECT agent_id, COUNT(*), SUM(units), SUM(cents) FROM usage WHERE buyer=? "
            "GROUP BY agent_id ORDER BY agent_id", (buyer,)).fetchall()
        st = Statement(buyer=buyer)
        total_fee = 0
        for agent_id, calls, units, gross in rows:
            # 分成按「行级四舍五入、余数留给开发者」——平台不靠舍入多拿钱
            platform = int(Decimal(gross * fee_pct / 100).quantize(CNY, rounding=ROUND_HALF_UP))
            total_fee += platform
            st.lines.append(Line(agent_id, developers.get(agent_id, "unknown"), calls, units,
                                 gross, platform, gross - platform))
        return st
