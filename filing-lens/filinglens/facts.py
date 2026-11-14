"""XBRL 财务事实：表格类问题走结构化查询，绝不走文本检索。

SEC companyfacts JSON 是免费的、官方的、结构化的。它能回答「近三年毛利率怎么变」，
而文本检索永远答不对这种问题。
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
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

# `start` 必须进主键：同一份 10-K 里，年报（≈363 天）和第 4 季度（≈90 天）
# 可以共享同一个 `end`、同一个 `fy`、同一个 `form`，只在时长上不同。
# 不带 start 时后写的那行会把前一行覆盖掉——这正是 +465.4% 的来源。
SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    cik TEXT, entity TEXT, tag TEXT, unit TEXT,
    fy INTEGER, fp TEXT, form TEXT, start TEXT, end TEXT,
    val REAL, filed TEXT,
    PRIMARY KEY (cik, tag, unit, fy, fp, start, end, form)
);
CREATE INDEX IF NOT EXISTS idx_facts_tag ON facts(cik, tag, fy);
"""

# 年报的时长口径：52/53 周（364/371 天）到 366 天都常见；季度是 ~90 天。
ANNUAL_MIN_DAYS = 330
ANNUAL_MAX_DAYS = 400


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """建表；老库（没有 start 列/主键少一列）就地重建，不丢已有行。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
    if cols and "start" not in cols:
        conn.executescript("DROP INDEX IF EXISTS idx_facts_tag;")
        conn.executescript("ALTER TABLE facts RENAME TO facts_old;")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO facts(cik,entity,tag,unit,fy,fp,form,start,end,val,filed) "
            "SELECT cik,entity,tag,unit,fy,fp,form,'',end,val,filed FROM facts_old")
        conn.execute("DROP TABLE facts_old")
        conn.commit()
        return
    conn.executescript(SCHEMA)


@dataclass
class Fact:
    tag: str
    fy: int
    val: float
    unit: str
    form: str
    end: str
    start: str = ""


def load_companyfacts(payload: dict, db_path: str | Path = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False：连接在载入线程里建，查询发生在 FastAPI 的请求线程池里。
    # 默认 True 时服务端会随机抛「SQLite objects created in a thread can only be used in
    # that same thread」——console 的 filing 面板每 3 次请求炸 1 次（实测 12 轮 3 次）。
    # 载入完成后本连接只做只读查询，因此允许跨线程使用是安全的。
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
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
                                 e["form"], e.get("start", "") or "", e.get("end", ""),
                                 float(e.get("val", 0)), e.get("filed", "")))
    conn.executemany(
        "INSERT OR REPLACE INTO facts(cik,entity,tag,unit,fy,fp,form,start,end,val,filed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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


def _duration_days(start: str, end: str) -> int | None:
    """一段事实覆盖的天数；时点类事实（没有 start）返回 None。"""
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _is_annual(start: str, end: str) -> bool:
    """没有 start 的时点事实（现金余额、资产总额）照旧算年度；有 start 的看时长。

    `fp='FY'` 不足以筛年报：SEC 的 companyfacts 把 10-K 里的**季度**值也标成 fp='FY'
    （Apple 的 2019Q3 就是），只有时长能把两者分开。实测按 fp 取 max(end) 时，
    FY2019 拿到 64.04B、FY2020 拿到 64.70B，同比印出 +465.4%。
    """
    days = _duration_days(start, end)
    return days is None or ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS


def annual_series(conn: sqlite3.Connection, metric: str) -> list[Fact]:
    """取某个指标的年报序列（只取年报口径）。

    真实 companyfacts 里同一个 fy 会有多行：同一份 10-K 会同时报 FY2026/FY2025/FY2024，
    后续 10-K 又重复报上一年的比较数，还有重述（restatement）。若直接按 fy 排序，
    相邻两行可能来自不同 `end`，算出来的同比会出现 -61.5% 这种离谱数字（Apple 实测踩到）。
    所以：先按时长剔掉季度值，再按 `end` 去重（同一期末只留最近申报那行）。
    """
    tags = METRIC_ALIASES.get(metric, [metric])
    # 外部调用方会拿一张最小的 facts 表来喂（scripts/review_diff.py 的测试就是自己建表），
    # 那种表没有 start 列。没有就按「时点事实」处理，不去改别人的建表语句。
    has_start = "start" in {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
    cols = ("tag,fy,val,unit,form,end,filed,start" if has_start
            else "tag,fy,val,unit,form,end,filed,'' AS start")
    for tag in tags:
        rows = conn.execute(
            f"SELECT {cols} FROM facts WHERE tag=? AND fp='FY'", (tag,)).fetchall()
        if not rows:
            continue
        by_end: dict[str, sqlite3.Row] = {}
        for r in rows:
            if not _is_annual(r["start"] or "", r["end"] or ""):
                continue
            cur = by_end.get(r["end"] or "")
            if cur is None or (r["filed"] or "") >= (cur["filed"] or ""):
                by_end[r["end"] or ""] = r
        if not by_end:
            continue
        kept = sorted(by_end.values(), key=lambda r: r["end"] or "")
        # 财年标签按时点锚定：最新期末的 fy 减去期末年份差。
        # 不能各取各的 fy——比较数那一行的 fy 常常是**申报年**，同一段历史会被标成两年。
        anchor = kept[-1]
        anchor_fy, anchor_year = int(anchor["fy"]), _end_year(anchor["end"])
        out: list[Fact] = []
        seen: dict[int, Fact] = {}
        for r in kept:
            year = _end_year(r["end"])
            fy = anchor_fy - (anchor_year - year) if year and anchor_year else int(r["fy"])
            fact = Fact(r["tag"], fy, r["val"], r["unit"], r["form"], r["end"] or "",
                        r["start"] or "")
            prev = seen.get(fy)
            if prev is None or (fact.end or "") >= (prev.end or ""):
                seen[fy] = fact
        out = [seen[fy] for fy in sorted(seen)]
        return out
    return []


def _end_year(end: str) -> int | None:
    try:
        return date.fromisoformat(end).year
    except (TypeError, ValueError):
        return None


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


_READ_ONLY_START = re.compile(r"^\s*(?:select|with|explain)\b", re.I)
_WRITE_KEYWORD = re.compile(
    r"\b(?:insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|analyze|begin|commit|rollback|savepoint|release|truncate)\b", re.I)
_SQL_STRING = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]|`[^`]*`")


def sql_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """只读查询。传进来的 SQL 只允许读 —— 写语句一律拒。

    原先直接 `conn.execute(sql, params)`：`DROP TABLE facts` 会执行成功，
    一条来自问题文本或外部清单的 SQL 就能清掉整张事实表。
    """
    body = _SQL_STRING.sub("''", sql or "")          # 先抹掉字符串字面量再判关键词
    if not _READ_ONLY_START.match(body):
        raise ValueError(f"只允许只读查询（SELECT / WITH / EXPLAIN），收到：{sql[:60]!r}")
    if _WRITE_KEYWORD.search(body):
        raise ValueError(f"SQL 里出现写操作关键字，拒绝执行：{sql[:60]!r}")
    if ";" in body.rstrip().rstrip(";"):
        raise ValueError(f"只允许单条语句：{sql[:60]!r}")
    return conn.execute(sql, params).fetchall()
