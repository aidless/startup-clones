"""用真实 XBRL 财务数据跑分析性程序（analytical procedures）。

输入是 SEC companyfacts JSON（filing-lens/scripts/fetch_edgar.py 会拉下来），
输出是「比率与趋势自相矛盾」的例外清单 —— 这就是审计里最省抽凭的那道程序。

    python scripts/real_analytics.py ../filing-lens/data/0000320193_facts.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditloop.analytics import Series, run_all  # noqa: E402

REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
           "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]
RECEIVABLES = ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
               "AccountsNotesAndLoansReceivableNetCurrent"]
GROSS_PROFIT = ["GrossProfit"]
CFO = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]


def annual(payload: dict, tags: list[str]) -> dict[int, float]:
    """取年度值：同一财年只留「最近申报 + 最新期末」那一行，且只认 10-K 的 FY。"""
    rows: dict[int, tuple[str, str, float]] = {}
    for tag in tags:
        block = payload.get("facts", {}).get("us-gaap", {}).get(tag)
        if not block:
            continue
        for unit_rows in block.get("units", {}).values():
            for r in unit_rows:
                if r.get("form") not in {"10-K", "10-K/A", "20-F"} or r.get("fp") != "FY":
                    continue
                fy = r.get("fy")
                if not fy:
                    continue
                key = (r.get("filed", ""), r.get("end", ""))
                cur = rows.get(fy)
                if cur is None or key > (cur[0], cur[1]):
                    rows[fy] = (key[0], key[1], float(r["val"]))
        if rows:
            break
    return {fy: v[2] for fy, v in sorted(rows.items())}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text())
    name = payload.get("entityName", "?")
    s = Series(
        revenue=annual(payload, REVENUE),
        receivables=annual(payload, RECEIVABLES),
        gross_profit=annual(payload, GROSS_PROFIT),
        cfo=annual(payload, CFO),
    )
    print(f"{name}  收入年数={len(s.revenue)}  应收={len(s.receivables or {})}  "
          f"毛利={len(s.gross_profit or {})}  经营现金流={len(s.cfo or {})}")
    print("收入序列:", {y: f"{v/1e6:.0f}M" for y, v in s.revenue.items()})
    findings = run_all(s)
    if not findings:
        print("\n没有分析性例外。")
        return 0
    print(f"\n{len(findings)} 条例外：")
    for f in findings:
        print(f"  [{f.severity:<6}] {f.ref}  {f.check}")
        print(f"           {f.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
