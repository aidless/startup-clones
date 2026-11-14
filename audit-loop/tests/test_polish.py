"""「打磨」时实测出的缺陷复现：现金科目匹配区分大小写。

`CASH_ACCOUNTS` 里既有中文（银行存款/现金）也有英文小写（cash/bank），
而判断写的是 `any(a in e.account for a in accounts)` —— 区分大小写。
真实底稿里科目名几乎都是 "Bank Account USD" / "Cash-1000" 这种写法，
于是一整批现金科目**一个都不匹配**，还全部落到「银行已记、企业未记」一侧，
看起来像"公司漏记了所有银行流水"这种重大例外。
"""
from __future__ import annotations

from datetime import date

from auditloop.checks import reconcile_bank
from auditloop.models import BankLine, Entry

D = date(2026, 9, 30)


def _entry(account: str, amount: float) -> Entry:
    return Entry(entry_id="E1", date=D, account=account, debit=amount, memo="收款")


def _line(amount: float) -> BankLine:
    return BankLine(line_id="B1", date=D, amount=amount, memo="收款")


def test_english_account_name_matches_case_insensitively():
    res = reconcile_bank([_entry("Bank Account USD", 1000.0)], [_line(1000.0)])
    assert len(res.matched) == 1, "英文科目名没匹配上：判断区分了大小写"
    assert res.unmatched_gl == []
    assert res.unmatched_bank == []


def test_uppercase_cash_account_matches():
    res = reconcile_bank([_entry("CASH-1000", 500.0)], [_line(500.0)])
    assert len(res.matched) == 1


def test_chinese_account_still_matches():
    """正对照：改完之后中文科目不能被弄坏。"""
    res = reconcile_bank([_entry("银行存款-工行", 800.0)], [_line(800.0)])
    assert len(res.matched) == 1


def test_non_cash_account_still_excluded():
    """正对照：非现金科目仍然不参与调节（配上一模一样的流水也不许匹配）。"""
    res = reconcile_bank([_entry("管理费用", 800.0)], [_line(800.0)])
    assert res.matched == []
