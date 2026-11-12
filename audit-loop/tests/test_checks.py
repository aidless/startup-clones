from datetime import date

import pytest

from auditloop import checks, fixtures


def test_bank_recon_matches_and_exceptions():
    rec = checks.reconcile_bank(fixtures.entries(), fixtures.bank_lines())
    assert len(rec.matched) == 2
    assert [e.entry_id for e, _ in rec.amount_diff] == ["G3"]
    assert abs((rec.amount_diff[0][1].date - rec.amount_diff[0][0].date).days) == 12
    # 只有现金类科目参与调节；管理费用 G7 / 收入 G8 不该出现在未达账项里
    assert {e.entry_id for e in rec.unmatched_gl} == {"G4", "G6"}
    assert [b.line_id for b in rec.unmatched_bank] == ["B4"]
    # 调节差额 = 未达账项净额，必须能被会计师手工验算
    assert rec.difference == pytest.approx(1055.00)


def test_aging_buckets():
    buckets = {b.label: b for b in checks.ar_aging(fixtures.invoices(), fixtures.AS_OF)}
    assert [len(buckets[k].invoices) for k in ("current", "1-30", "31-60", "61-90", ">90")] == [1, 2, 1, 1, 1]
    assert buckets[">90"].total == 2000
    assert [i.invoice_id for i in buckets["31-60"].invoices] == ["INV-1003"]


def test_aging_boundary_days():
    inv = fixtures.invoices()[4]  # due 2026-06-30
    at_90 = checks.ar_aging([inv], date(2026, 9, 28))
    at_91 = checks.ar_aging([inv], date(2026, 9, 29))
    assert at_90[3].label == "61-90" and len(at_90[3].invoices) == 1
    assert at_91[4].label == ">90" and len(at_91[4].invoices) == 1


def test_revenue_cutoff_finds_exactly_two():
    fs = checks.revenue_cutoff(fixtures.invoices(), fixtures.PERIOD_END)
    assert {f.ref for f in fs} == {"INV-1003", "INV-1004"}
    assert all(f.severity == "high" and f.assertion == "截止" for f in fs)


def test_duplicate_payment_detected():
    fs = checks.duplicate_payments(fixtures.entries())
    assert len(fs) == 1
    assert fs[0].ref == "G3/G6"
    assert fs[0].amount == pytest.approx(800)


def test_sanity_and_completeness():
    invs = fixtures.invoices()
    assert [f.ref for f in checks.ar_negative_or_zero(invs)] == ["INV-1006"]
    assert [f.ref for f in checks.missing_due_date(invs)] == ["INV-1006"]


def test_vendor_concentration_sums_to_one():
    rows = checks.vendor_concentration(fixtures.entries())
    assert sum(r[2] for r in rows) == pytest.approx(1.0, abs=1e-4)
    assert rows[0][0] == "Northwind"
