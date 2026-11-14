"""计量与账单：价格由清单决定，分成由平台决定，第二次相同的 request_id 不重复计费。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
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
    -- 执行结果也落库：幂等若只记在进程内字典里，重启 / 多副本 / 换 worker 后
    -- 同一 request_id 会重跑 handler（副作用执行两次），且回放标志为假。
    ok         INTEGER NOT NULL DEFAULT 1,
    output     TEXT NOT NULL DEFAULT '',
    error      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (buyer, request_id)
);
CREATE TABLE IF NOT EXISTS statements (
    -- 出账是「变更」：一旦按 request_id 落成快照，同一个 id 再来只回放它。
    -- 键scope 到 buyer，理由与 usage 相同：B 撞上 A 的账单号不能读到 A 的数。
    request_id      TEXT NOT NULL,
    buyer           TEXT NOT NULL,
    fee_pct         INTEGER NOT NULL,
    gross_cents     INTEGER NOT NULL,
    platform_cents  INTEGER NOT NULL,
    developer_cents INTEGER NOT NULL,
    rows_json       TEXT NOT NULL,
    ts              TEXT NOT NULL,
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
    ok: bool = True
    output: str = ""
    error: str = ""


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
    fee_pct: int = 20
    request_id: str | None = None
    issued_at: str = ""
    idempotent_replay: bool = False

    @property
    def gross_cents(self) -> int:
        return sum(l.gross_cents for l in self.lines)

    @property
    def platform_cents(self) -> int:
        return sum(l.platform_cents for l in self.lines)

    @property
    def developer_cents(self) -> int:
        return sum(l.developer_cents for l in self.lines)

    def to_dict(self) -> dict:
        """JSON 与 Markdown 共用这一份数：两边各算一次迟早分叉。"""
        return {
            "buyer": self.buyer,
            "fee_pct": self.fee_pct,
            "gross_cents": self.gross_cents,
            "platform_cents": self.platform_cents,
            "developer_cents": self.developer_cents,
            "request_id": self.request_id,
            "issued_at": self.issued_at,
            "idempotent_replay": self.idempotent_replay,
            "rows": [asdict(l) for l in self.lines],
        }

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
        self._migrate_usage()
        self._now = now
        self._manifests: dict[tuple[str, str], AgentManifest] = {}

    def _migrate_usage(self) -> None:
        """老库里的 usage 没有 ok/output/error 三列：补上，别让旧账单库打不开。"""
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(usage)").fetchall()}
        for col, ddl in (("ok", "INTEGER NOT NULL DEFAULT 1"),
                         ("output", "TEXT NOT NULL DEFAULT ''"),
                         ("error", "TEXT NOT NULL DEFAULT ''")):
            if col not in have:
                self.conn.execute(f"ALTER TABLE usage ADD COLUMN {col} {ddl}")
        self.conn.commit()

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
               request_id: str, units: int, cents: int | None = None,
               ok: bool = True, output: str = "", error: str = "") -> UsageRecord:
        """记一次调用。cents 仅用于测试按分计价的边界（默认按清单算价）。"""
        seen = self.replay(buyer, request_id)
        if seen is not None:
            return seen
        if cents is None:
            cents = self.price(agent_id, version, units)
        self.conn.execute(
            "INSERT INTO usage(request_id,buyer,agent_id,version,units,cents,ts,ok,output,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (request_id, buyer, agent_id, version, units, cents, self._now,
             1 if ok else 0, output, error))
        self.conn.commit()
        return UsageRecord(request_id, buyer, agent_id, version, units, cents,
                           ok=ok, output=output, error=error)

    def replay(self, buyer: str, request_id: str) -> UsageRecord | None:
        """按 (buyer, request_id) 取已落库的执行记录；没有则 None。

        这张表就是幂等的**权威**：Runtime 的重投判断以它为准，进程内字典只当缓存。
        """
        row = self.conn.execute(
            "SELECT request_id,buyer,agent_id,version,units,cents,ok,output,error "
            "FROM usage WHERE buyer=? AND request_id=?", (buyer, request_id)).fetchone()
        if row is None:
            return None
        return UsageRecord(row[0], row[1], row[2], row[3], row[4], row[5], duplicate=True,
                           ok=bool(row[6]), output=row[7] or "", error=row[8] or "")

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

    def issue_statement(self, buyer: str, developers: dict[str, str],
                        fee_pct: int = 20, request_id: str | None = None) -> Statement:
        """出账。给了 request_id 就是「变更」：按 (buyer, request_id) 落快照，
        同一个 id 再来原样回放（不回炉重算，也不吃新用量）。没有 request_id 只读。"""
        if request_id is not None:
            row = self.conn.execute(
                "SELECT fee_pct,gross_cents,platform_cents,developer_cents,rows_json,ts "
                "FROM statements WHERE buyer=? AND request_id=?",
                (buyer, request_id)).fetchone()
            if row is not None:
                return Statement(buyer, [Line(**d) for d in json.loads(row[4])],
                                 fee_pct=row[0], request_id=request_id,
                                 issued_at=row[5], idempotent_replay=True)
        st = self.statement(buyer, developers, fee_pct)
        st.fee_pct, st.request_id, st.issued_at = fee_pct, request_id, self._now
        if request_id is not None:
            data = st.to_dict()
            self.conn.execute(
                "INSERT INTO statements(request_id,buyer,fee_pct,gross_cents,platform_cents,"
                "developer_cents,rows_json,ts) VALUES(?,?,?,?,?,?,?,?)",
                (request_id, buyer, fee_pct, data["gross_cents"], data["platform_cents"],
                 data["developer_cents"], json.dumps(data["rows"], ensure_ascii=False),
                 self._now))
            self.conn.commit()
        return st
