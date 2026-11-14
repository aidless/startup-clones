"""三个高频审计程序：银行存款余额调节、应收账款账龄、收入截止测试。

全部纯函数、无 IO、无随机 —— 同样的输入永远给同样的例外清单。
会计师复核的是「你为什么把这一条列为例外」，不是「模型觉得」。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import (CLASSIFICATION, COMPLETENESS, CUTOFF, EXISTENCE, VALUATION,
                     BankLine, Entry, Finding, Invoice)

TOL = 0.01


@dataclass
class ReconResult:
    matched: list[tuple[Entry, BankLine]] = field(default_factory=list)
    unmatched_gl: list[Entry] = field(default_factory=list)
    unmatched_bank: list[BankLine] = field(default_factory=list)
    amount_diff: list[tuple[Entry, BankLine]] = field(default_factory=list)

    @property
    def gl_total(self) -> float:
        return round(sum(e.amount for e in self.unmatched_gl), 2)

    @property
    def bank_total(self) -> float:
        return round(sum(b.amount for b in self.unmatched_bank), 2)

    @property
    def difference(self) -> float:
        """调节后差额：应等于未达账项净额。"""
        return round(self.bank_total - self.gl_total, 2)


CASH_ACCOUNTS = ("银行存款", "现金", "cash", "bank")


def reconcile_bank(entries: list[Entry], lines: list[BankLine], window_days: int = 3,
                   accounts: tuple[str, ...] = CASH_ACCOUNTS) -> ReconResult:
    """按金额 + 日期窗口做 1:1 匹配；金额相同但日期超出窗口记为「时间性差异」。

    只对现金类科目做调节 —— 把管理费用/收入科目拿去跟银行流水碰，会造出一堆假例外。
    """
    res = ReconResult()
    used: set[int] = set()
    # 科目名大小写不敏感：底稿里几乎都写 "Bank Account USD" / "CASH-1000"，
    # 而 CASH_ACCOUNTS 里是小写 cash/bank —— 区分大小写时一整批现金科目一个都不匹配，
    # 还全部落到「银行已记、企业未记」一侧，看起来像"漏记了所有银行流水"。
    accounts_cf = tuple(a.casefold() for a in accounts)
    cash = [e for e in entries if any(a in e.account.casefold() for a in accounts_cf)]
    for e in sorted(cash, key=lambda x: x.date):
        best: tuple[int, int] | None = None
        for i, b in enumerate(lines):
            if i in used or abs(b.amount - e.amount) > TOL:
                continue
            delta = abs((b.date - e.date).days)
            if best is None or delta < best[1]:
                best = (i, delta)
        if best is None:
            res.unmatched_gl.append(e)
            continue
        idx, delta = best
        used.add(idx)
        if delta <= window_days:
            res.matched.append((e, lines[idx]))
        else:
            res.amount_diff.append((e, lines[idx]))
    res.unmatched_bank = [b for i, b in enumerate(lines) if i not in used]
    return res


@dataclass
class AgingBucket:
    label: str
    invoices: list[Invoice] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(i.amount for i in self.invoices), 2)


BUCKETS = [("current", None, 0), ("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), (">90", 91, None)]


UNKNOWN_DUE_LABEL = "无到期日"


def ar_aging(invoices: list[Invoice], as_of: date) -> list[AgingBucket]:
    """按到期日计算逾期天数。未到期归 current，缺到期日单列一桶。

    缺到期日的发票不进任何逾期桶：算不出账龄就报不出逾期，硬塞进 current
    会让「未到期」这个结论凭空成立。单列一桶，让会计师一眼看到有多少笔算不了。
    """
    out = [AgingBucket(label=lbl) for lbl, _, _ in BUCKETS]
    out.append(AgingBucket(label=UNKNOWN_DUE_LABEL))
    for inv in invoices:
        if inv.due_date is None:
            out[-1].invoices.append(inv)
            continue
        days = (as_of - inv.due_date).days
        for bucket, (_, lo, hi) in zip(out, BUCKETS):
            if lo is None:
                continue
            if hi is None and days >= lo:
                bucket.invoices.append(inv)
                break
            if days >= lo and days <= hi:
                bucket.invoices.append(inv)
                break
        else:
            out[0].invoices.append(inv)
    return out


def revenue_cutoff(invoices: list[Invoice], period_end: date, tolerance_days: int = 0) -> list[Finding]:
    """截止测试：确认收入但发货在期末之后（含未发货）→ 截止例外。

    tolerance_days 允许会计师按重要性设宽限（例如期末后 1 天内发货不调整）。
    """
    findings: list[Finding] = []
    for inv in invoices:
        if not inv.recognized:
            continue
        if inv.shipped_date is None:
            # 未发货分支同样必须先过「收入是否落在本期内」——原实现直接报，
            # 下期收入（2027-01-15，期末 2026-09-30）被成本期截止例外，
            # 而本期收入确认 + 无发货记录才是真例外。
            if inv.revenue_date > period_end:
                continue
            findings.append(Finding(
                check="revenue_cutoff", assertion=CUTOFF, ref=inv.invoice_id, severity="high",
                detail=f"{inv.customer} 已确认收入但无发货记录（期末 {period_end}）", amount=inv.amount))
            continue
        if inv.shipped_date > period_end + timedelta(days=tolerance_days) and inv.revenue_date <= period_end:
            findings.append(Finding(
                check="revenue_cutoff", assertion=CUTOFF, ref=inv.invoice_id, severity="high",
                detail=(f"{inv.customer} 收入确认日 {inv.revenue_date} 早于发货日 {inv.shipped_date}，"
                        f"期末 {period_end} 前未发货却确认收入"), amount=inv.amount))
    return findings


def duplicate_payments(entries: list[Entry], window_days: int = 5) -> list[Finding]:
    """同一供应商、同金额、短期内重复付款 —— 存在性/计价的高频舞弊信号。"""
    groups: dict[tuple[str, float], list[Entry]] = defaultdict(list)
    for e in entries:
        if e.amount < 0 and e.vendor:
            groups[(e.vendor, round(abs(e.amount), 2))].append(e)
    findings: list[Finding] = []
    for (vendor, amt), items in groups.items():
        items.sort(key=lambda x: x.date)
        for prev, cur in zip(items, items[1:]):
            if (cur.date - prev.date).days <= window_days:
                findings.append(Finding(
                    check="duplicate_payment", assertion=EXISTENCE, ref=f"{prev.entry_id}/{cur.entry_id}",
                    severity="high",
                    detail=f"{vendor} 在 {prev.date} 与 {cur.date} 各付 {amt:,.2f}，疑似重复付款",
                    amount=amt))
    return findings


def ar_negative_or_zero(invoices: list[Invoice]) -> list[Finding]:
    out = [Finding(check="ar_sanity", assertion=VALUATION, ref=i.invoice_id, severity="medium",
                   detail=f"{i.customer} 发票金额异常：{i.amount:,.2f}", amount=i.amount)
           for i in invoices if i.amount <= 0]
    return out


def missing_due_date(invoices: list[Invoice]) -> list[Finding]:
    """到期日缺失或倒挂 —— 两种都让账龄不可靠，但原因不同，必须分开写。"""
    out: list[Finding] = []
    for i in invoices:
        if i.due_date is None:
            out.append(Finding(check="ar_completeness", assertion=COMPLETENESS,
                               ref=i.invoice_id, severity="medium",
                               detail=f"{i.customer} 到期日缺失，无法计算账龄", amount=i.amount))
        elif i.due_date < i.issue_date:
            out.append(Finding(check="ar_completeness", assertion=COMPLETENESS,
                               ref=i.invoice_id, severity="low",
                               detail=f"{i.customer} 到期日早于开票日，账龄不可靠", amount=i.amount))
    return out


def classification_summary(entries: list[Entry]) -> dict[str, float]:
    """按科目汇总借贷净额 —— 底稿第一页永远需要这张表。"""
    agg: dict[str, float] = defaultdict(float)
    for e in entries:
        agg[e.account] += e.amount
    return {k: round(v, 2) for k, v in sorted(agg.items())}


def vendor_concentration(entries: list[Entry]) -> list[tuple[str, float, float]]:
    """供应商集中度：帮助判断是否存在未披露的关联方。"""
    spend: Counter = Counter()
    for e in entries:
        if e.amount < 0 and e.vendor:
            spend[e.vendor] += abs(e.amount)
    total = sum(spend.values()) or 1.0
    return [(v, round(a, 2), round(a / total, 4)) for v, a in spend.most_common()]
