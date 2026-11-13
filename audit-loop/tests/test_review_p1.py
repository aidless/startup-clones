"""审查报告 P1（audit-loop）六条的复现测试（2026-11-12 审查）。

对着「会让底稿崩或给出反向结论」的六处：
缺到期日、负经营现金流符号、None 混进序列、注释与实现不一致、
枚举外严重度、失败追踪丢失。
"""
from __future__ import annotations

from datetime import date

import pytest
from openpyxl import load_workbook

from auditloop import checks, fixtures
from auditloop.analytics import Series, cash_conversion, revenue_vs_receivables
from auditloop.engine import AuditRun
from auditloop.models import EXISTENCE, Finding
from auditloop.workpaper import write_workpaper


# ---------------- P1-a 缺到期日不能崩 ----------------

def test_aging_tolerates_missing_due_date():
    """AR 导出常见「到期日空着」。原实现 `as_of - inv.due_date` 直接 TypeError，
    整张账龄表连带底稿一起报错——而缺到期日本身就该是一条完整性例外。"""
    inv = checks.Invoice(invoice_id="INV-N1", customer="Acme", amount=100.0,
                         issue_date=date(2026, 7, 1), due_date=None)
    buckets = checks.ar_aging([inv], date(2026, 9, 30))
    labels = [b.label for b in buckets]
    assert "无到期日" in labels
    unknown = next(b for b in buckets if b.label == "无到期日")
    assert [i.invoice_id for i in unknown.invoices] == ["INV-N1"]
    assert unknown.total == 100.0


def test_missing_due_date_is_reported_not_crashed():
    inv = checks.Invoice(invoice_id="INV-N2", customer="Acme", amount=100.0,
                         issue_date=date(2026, 7, 1), due_date=None)
    fs = checks.missing_due_date([inv])
    assert [f.ref for f in fs] == ["INV-N2"]
    assert "到期日" in fs[0].detail
    assert fs[0].assertion == "完整性"


def test_due_before_issue_still_reported():
    # 正对照：「到期日早于开票日」这条既有判据不许被打包进「缺失」而丢掉
    assert [f.ref for f in checks.missing_due_date(fixtures.invoices())] == ["INV-1006"]
    assert "早于开票日" in checks.missing_due_date(fixtures.invoices())[0].detail


# ---------------- P1-b 负经营现金流的相对变化 ----------------

def test_negative_cfo_improvement_is_not_a_decline():
    """-0.50 → -0.20 是改善。原实现 `(pr - cr) / pr` 在 pr<0 时符号翻转，
    算出 +60% 相对下滑，报「利润的现金含量下降」——结论与事实相反。"""
    s = Series(revenue={2024: 1000.0, 2025: 1000.0},
               cfo={2024: -500.0, 2025: -200.0})
    assert cash_conversion(s) == []


def test_negative_cfo_worsening_is_reported():
    """-0.10 → -0.20 是恶化：绝对变化 0.10 卡在阈值边界（> 才报），
    但相对恶化 100%，必须报。"""
    s = Series(revenue={2024: 1000.0, 2025: 1000.0},
               cfo={2024: -100.0, 2025: -200.0})
    fs = cash_conversion(s)
    assert len(fs) == 1
    assert "下滑" in fs[0].detail or "恶化" in fs[0].detail
    assert "-0.10" in fs[0].detail and "-0.20" in fs[0].detail


def test_positive_cfo_decline_unchanged():
    # 正对照：正现金流的老判据不许变
    s = Series(revenue={2024: 1000.0, 2025: 1000.0}, cfo={2024: 250.0, 2025: 180.0})
    fs = cash_conversion(s)
    assert len(fs) == 1 and "0.25" in fs[0].detail and "0.18" in fs[0].detail


# ---------------- P1-c None 混进序列 ----------------

def test_none_in_series_is_skipped_not_crashed():
    """`revenue` 里某年 None（导出缺列）时原实现直接崩；
    同模块的 `cash_conversion` 却静默跳过——两个程序对同一份脏数据给出不同命运。"""
    s = Series(revenue={2024: 1000.0, 2025: None, 2026: 1200.0},
               receivables={2024: 100.0, 2025: 150.0, 2026: 300.0},
               gross_profit={2024: 400.0, 2025: None, 2026: 500.0},
               cfo={2024: 100.0, 2025: None, 2026: 120.0})
    findings = checks_analytics_run_all(s)
    assert all(isinstance(f.ref, str) for f in findings)   # 只要不抛就算过


def checks_analytics_run_all(s: Series):
    from auditloop.analytics import run_all
    return run_all(s)


def test_none_in_cfo_pair_is_skipped():
    s = Series(revenue={2024: 1000.0, 2025: 1000.0}, cfo={2024: None, 2025: 180.0})
    assert cash_conversion(s) == []


# ---------------- P1-d 注释与实现必须一致 ----------------

def test_single_year_divergence_is_reported():
    """行为以「逐年判 + 阈值过滤」为准（这是审计实际要的：单年大背离就是信号），
    注释同步改成这个口径，不再声称「连续两年同向才报」。"""
    s = Series(revenue={2024: 1000.0, 2025: 1050.0},
               receivables={2024: 100.0, 2025: 145.0})
    assert len(revenue_vs_receivables(s)) == 1


def test_sub_threshold_blip_not_reported():
    # 阈值下面是噪声，不许报
    s = Series(revenue={2024: 1000.0, 2025: 1050.0},
               receivables={2024: 100.0, 2025: 120.0})
    assert revenue_vs_receivables(s) == []


def test_threshold_constant_is_documented_as_per_year():
    import inspect
    from auditloop import analytics
    doc = inspect.getdoc(analytics) or ""
    assert "只在连续两年都同向时才报" not in doc, "文档仍声称按连续两年判，与实现不符"
    assert "逐年" in doc or "每一年" in doc or "相邻" in doc


# ---------------- P1-e 枚举外严重度 ----------------

def _run_with_severity(sev: str) -> AuditRun:
    run = AuditRun(entity="T", period_end=date(2026, 9, 30))
    run.register("step", EXISTENCE, lambda: [
        Finding(check="step", assertion=EXISTENCE, ref="X1", severity=sev, detail="测试"),
    ]).run()
    return run


def test_unknown_severity_does_not_break_markdown():
    md = _run_with_severity("critical").to_markdown()
    assert "critical" in md


def test_unknown_severity_does_not_break_workpaper(tmp_path):
    p = write_workpaper(_run_with_severity("critical"), tmp_path / "wp.xlsx")
    ws = load_workbook(p)["例外"]
    assert ws.cell(row=2, column=3).value == "critical"


def test_known_severities_still_ordered():
    # 正对照：high 仍排在 medium 前面
    run = AuditRun(entity="T", period_end=date(2026, 9, 30))
    run.register("step", EXISTENCE, lambda: [
        Finding("step", EXISTENCE, "L", "low", "低"),
        Finding("step", EXISTENCE, "H", "high", "高"),
        Finding("step", EXISTENCE, "M", "medium", "中"),
    ]).run()
    md = run.to_markdown()
    assert md.index("| H |") < md.index("| M |") < md.index("| L |")


# ---------------- P1-f 失败追踪不许丢 ----------------

def test_failed_step_trace_is_kept_and_rendered():
    def boom():
        raise ValueError("CSV 有脏行")

    run = (AuditRun(entity="T", period_end=date(2026, 9, 30))
           .register("bad_step", EXISTENCE, boom).run())
    bad = run.results[0]
    assert bad.trace and "ValueError" in bad.trace
    md = run.to_markdown()
    assert "bad_step" in md and ("Traceback" in md or "ValueError" in md)


def test_workpaper_carries_error_and_trace(tmp_path):
    def boom():
        raise ValueError("CSV 有脏行")

    run = (AuditRun(entity="T", period_end=date(2026, 9, 30))
           .register("bad_step", EXISTENCE, boom).run())
    p = write_workpaper(run, tmp_path / "wp.xlsx")
    wb = load_workbook(p)
    summary = wb["摘要"]
    texts = [str(c.value) for row in summary.iter_rows() for c in row if c.value]
    assert any("ValueError" in t for t in texts), "摘要里看不到失败原因"
    detail = wb["明细"]
    dtexts = [str(c.value) for row in detail.iter_rows() for c in row if c.value]
    assert any("Traceback" in t or "ValueError" in t for t in dtexts), "明细里没有追踪"
