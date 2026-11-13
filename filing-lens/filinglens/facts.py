"""XBRL 财务事实：表格类问题走结构化查询，绝不走文本检索。

SEC companyfacts JSON 是免费的、官方的、结构化的。它能回答「近三年毛利率怎么变」，
而文本检索永远答不对这种问题。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# 指标别名：中文/英文/口语 → us-gaap 标签候选（按优先级）
METRIC_ALIASES: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "营收": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "收入": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "gross profit": ["GrossProfit"],
    "毛利率": ["GrossProfit"],
    "net income": ["NetIncomeLoss"],
    "净利": ["NetIncomeLoss"],
    "r&d": ["ResearchAndDevelopmentExpense"],
    "rd expense": ["ResearchAndDevelopmentExpense"],
    "operating income": ["OperatingIncomeLoss"],
    "毛利": ["GrossProfit"],
    "net_income": ["NetIncomeLoss"],
    "净利润": ["NetIncomeLoss"],
    "r_and_d": ["ResearchAndDevelopmentExpense"],
    "研发": ["ResearchAndDevelopmentExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "营业利润": ["OperatingIncomeLoss"],
    "assets": ["Assets"],
    "总资产": ["Assets"],
    # 现金流与现金余额是两个科目，混了就是差 4 倍（Apple FY2026：145.1B vs 36.3B）。
    # 长别名优先（resolve_metric 取最长命中），所以 "cash flow from operations" 不会被 "cash" 抢走。
    "cash flow from operations": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash flow from operating activities": ["NetCashProvidedByUsedInOperatingActivities"],
    "operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash provided by operating activities": ["NetCashProvidedByUsedInOperatingActivities"],
    "经营现金流": ["NetCashProvidedByUsedInOperatingActivities"],
    "经营活动现金流": ["NetCashProvidedByUsedInOperatingActivities"],
    "经营活动产生的现金流": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "现金": ["CashAndCashEquivalentsAtCarryingValue"],
    "inventory": ["InventoryNet"],
    "存货": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "应收账款": ["AccountsReceivableNetCurrent"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    cik TEXT, entity TEXT, tag TEXT, unit TEXT,
    fy INTEGER, fp TEXT, form TEXT, end TEXT,
    val REAL, filed TEXT,
    PRIMARY KEY (cik, tag, unit, fy, fp, end, form)
);
CREATE INDEX IF NOT EXISTS idx_facts_tag ON facts(cik, tag, fy);
"""


@dataclass
class Fact:
    tag: str
    fy: int
    val: float
    unit: str
    form: str
    end: str


def load_companyfacts(payload: dict, db_path: str | Path = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False：连接在载入线程里建，查询发生在 FastAPI 的请求线程池里。
    # 默认 True 时服务端会随机抛「SQLite objects created in a thread can only be used in
    # that same thread」——console 的 filing 面板每 3 次请求炸 1 次（实测 12 轮 3 次）。
    # 载入完成后本连接只做只读查询，因此允许跨线程使用是安全的。
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cik = str(payload.get("cik", "")).zfill(10)
    entity = payload.get("entityName", "")
    rows = []
    for ns, tags in payload.get("facts", {}).items():
        for tag, node in tags.items():
            for unit, entries in node.get("units", {}).items():
                for e in entries:
                    if e.get("form") not in {"10-K", "10-K/A", "20-F"}:
                        continue
                    if not e.get("fy"):
                        continue
                    rows.append((cik, entity, tag, unit, int(e["fy"]), e.get("fp", ""),
                                 e["form"], e.get("end", ""), float(e.get("val", 0)), e.get("filed", "")))
    conn.executemany(
        "INSERT OR REPLACE INTO facts(cik,entity,tag,unit,fy,fp,form,end,val,filed) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


def resolve_metric(question: str) -> tuple[str, str] | None:
    """从问题里认出指标 → (alias, tag_candidate_order_key)。"""
    q = question.lower()
    best: tuple[int, str] | None = None
    for alias in METRIC_ALIASES:
        if alias in q and (best is None or len(alias) > best[0]):
            best = (len(alias), alias)
    if not best:
        return None
    return "metric", best[1]


def annual_series(conn: sqlite3.Connection, metric: str) -> list[Fact]:
    """取某个指标的年报序列。

    真实 companyfacts 里同一个 fy 会有多行：同一份 10-K 会同时报 FY2026/FY2025/FY2024，
    后续 10-K 又重复报上一年的比较数，还有重述（restatement）。若直接按 fy 排序，
    相邻两行可能来自不同 `end`，算出来的同比会出现 -61.5% 这种离谱数字（Apple 实测踩到）。
    所以：每个 fy 只保留「最近申报（filed 最大）且期末（end 最大）」的那一行。
    """
    tags = METRIC_ALIASES.get(metric, [metric])
    for tag in tags:
        rows = conn.execute(
            "SELECT tag,fy,val,unit,form,end,filed FROM facts WHERE tag=? AND fp='FY'",
            (tag,),
        ).fetchall()
        if not rows:
            continue
        best: dict[int, sqlite3.Row] = {}
        for r in rows:
            cur = best.get(r["fy"])
            key = (r["filed"] or "", r["end"] or "")
            if cur is None or key > (cur["filed"] or "", cur["end"] or ""):
                best[r["fy"]] = r
        return [Fact(r["tag"], r["fy"], r["val"], r["unit"], r["form"], r["end"])
                for _, r in sorted(best.items())]
    return []


def yoy(series: list[Fact]) -> list[tuple[int, float | None]]:
    """同比变化。上年为负或零时返回 None。

    用 abs 做分母能把 Intel 从 -18.8B 亏到 -267M 算成 "-1210.5%"，读起来像灾难，
    但那只是「亏得少了」——负基数上的百分比变化没有经济含义，宁可标不可算。
    """
    out: list[tuple[int, float | None]] = []
    for prev, cur in zip(series, series[1:]):
        if prev.val > 0:
            out.append((cur.fy, round((cur.val - prev.val) / prev.val, 4)))
        else:
            out.append((cur.fy, None))
    return out


def fmt_money(v: float, unit: str = "USD") -> str:
    if abs(v) >= 1e9:
        return f"{v/1e9:,.2f}B {unit}"
    if abs(v) >= 1e6:
        return f"{v/1e6:,.1f}M {unit}"
    return f"{v:,.0f} {unit}"


def sql_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()
