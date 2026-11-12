"""夹具：一家虚构公司（Acme Industrial）的一个季度末数据，故意埋入 6 类例外。

每一条埋点都在 tests 里被断言到具体 ref —— 夹具不许「差不多」，
否则检测能力就没被证明。
"""
from __future__ import annotations

from datetime import date

from .models import BankLine, Entry, Invoice

PERIOD_END = date(2026, 9, 30)
AS_OF = date(2026, 10, 31)


def entries() -> list[Entry]:
    return [
        Entry("G1", date(2026, 9, 2), "银行存款", debit=5000, memo="客户回款 A"),
        Entry("G2", date(2026, 9, 10), "银行存款", credit=1200, memo="付 Northwind 货款", vendor="Northwind"),
        Entry("G3", date(2026, 9, 20), "银行存款", credit=800, memo="顾问费", vendor="Northwind"),
        Entry("G4", date(2026, 9, 25), "银行存款", credit=300, memo="办公用品", vendor="Staples"),
        Entry("G6", date(2026, 9, 21), "银行存款", credit=800, memo="顾问费（重复录入）", vendor="Northwind"),
        Entry("G7", date(2026, 9, 12), "管理费用", debit=3300, memo="按月结转"),
        Entry("G8", date(2026, 9, 30), "营业收入", credit=28000, memo="本期确认收入"),
    ]


def bank_lines() -> list[BankLine]:
    return [
        BankLine("B1", date(2026, 9, 3), 5000, "客户回款"),
        BankLine("B2", date(2026, 9, 10), -1200, "Northwind"),
        BankLine("B3", date(2026, 10, 2), -800, "顾问费（跨月）"),
        BankLine("B4", date(2026, 9, 30), -45, "银行手续费"),
    ]


def invoices() -> list[Invoice]:
    return [
        # 正常：未到期、期末前发货并确认
        Invoice("INV-1001", "Blue Harbor", 10_000, date(2026, 9, 1), date(2026, 11, 15),
                shipped_date=date(2026, 9, 28), revenue_date=date(2026, 9, 28)),
        # 逾期 6 天
        Invoice("INV-1002", "Ridgeway", 5_000, date(2026, 8, 25), date(2026, 10, 25),
                shipped_date=date(2026, 8, 20), revenue_date=date(2026, 8, 25)),
        # 逾期 36 天 + 截止例外（发货晚于期末，收入确认在期末）
        Invoice("INV-1003", "Cobalt Labs", 7_500, date(2026, 8, 10), date(2026, 9, 25),
                shipped_date=date(2026, 10, 5), revenue_date=date(2026, 9, 30)),
        # 逾期 67 天 + 截止例外（无发货记录）
        Invoice("INV-1004", "Dunmore", 3_000, date(2026, 7, 1), date(2026, 8, 25),
                shipped_date=None, revenue_date=date(2026, 9, 29)),
        # 逾期 123 天
        Invoice("INV-1005", "Eastvale", 2_000, date(2026, 5, 20), date(2026, 6, 30),
                shipped_date=date(2026, 5, 18), revenue_date=date(2026, 5, 20)),
        # 金额为 0 + 到期日早于开票日（数据完整性例外）
        Invoice("INV-1006", "Fenwick", 0, date(2026, 10, 10), date(2026, 10, 5),
                shipped_date=date(2026, 10, 8), revenue_date=date(2026, 10, 8)),
    ]
