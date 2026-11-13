"""计量与账单：价格由清单决定，分成由平台决定，第二次相同的 request_id 不重复计费。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from .manifest import AgentManifest

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    -- 幂等键是 (buyer, request_id)：只按 request_id 时，B 撞上 A 的单号就永久免单
    request_id TEXT NOT NULL,
    buyer      TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    version    TEXT NOT NULL,
    units      INTEGER NOT NULL,
    cents      INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    PRIMARY KEY (buyer, request_id)
);
"""

CNY = Decimal("0.01")


def _money(cents: int) -> str:
    # 不用 cents / 100：float 在 2**53 美分（约 90 万亿元）以上丢精度，
    # 账单金额与流水对不上。整数除 Decimal，全程精确。
    amount = Decimal(int(cents)) / Decimal(100)
    return f"${amount:,.2f}"


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
               request_id: str, units: int, cents: int | None = None) -> UsageRecord:
        """记一次调用。cents 仅用于测试按分计价的边界（默认按清单算价）。"""
        row = self.conn.execute(
            "SELECT cents FROM usage WHERE buyer=? AND request_id=?",
            (buyer, request_id)).fetchone()
        if row:
            return UsageRecord(request_id, buyer, agent_id, version, units, row[0], duplicate=True)
        if cents is None:
            cents = self.price(agent_id, version, units)
        self.conn.execute(
            "INSERT INTO usage(request_id,buyer,agent_id,version,units,cents,ts) "
            "VALUES(?,?,?,?,?,?,?)",
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
        # 分成必须按「先汇总再取整」：行级取整时 100 行 ×1¢ @20% 每行都是 0.2¢→0，
        # 平台实收 0 分（实测复现）。汇总后按累计额分配，余数最后一行兜底，
        # 保证 sum(platform) + sum(developer) == gross。
        total_gross = sum(r[3] for r in rows)
        target_fee = int(Decimal(total_gross * fee_pct / 100).quantize(CNY, rounding=ROUND_HALF_UP))
        remaining = target_fee
        for idx, (agent_id, calls, units, gross) in enumerate(rows):
            if idx == len(rows) - 1:
                platform = remaining          # 末行兜底，保证总分成精确
            else:
                platform = int(Decimal(gross * fee_pct / 100).quantize(CNY, rounding=ROUND_HALF_UP))
                platform = min(platform, remaining)
            remaining -= platform
            total_fee += platform
            st.lines.append(Line(agent_id, developers.get(agent_id, "unknown"), calls, units,
                                 gross, platform, gross - platform))
        return st
