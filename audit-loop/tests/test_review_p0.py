"""审查报告 P0-13 的复现测试（2026-11-12 审查）。

截止测试的判据是「收入落在本期内、货却在本期后发出」。
未发货分支先 return，没做「收入是否落在本期」的判断 —— 下期收入（2027-01-15）
被报成本期（2026-09-30）截止例外。会计师能复核掉，但这是最常见的噪声来源：
噪声多了，真例外就被淹掉。
"""
from __future__ import annotations

from datetime import date

from auditloop.checks import revenue_cutoff
from auditloop.models import Invoice

PERIOD_END = date(2026, 9, 30)


def _inv(**kw) -> Invoice:
    base = dict(invoice_id="INV-1", customer="Acme", amount=1000.0,
                issue_date=date(2026, 9, 1), due_date=date(2026, 10, 1))
    base.update(kw)
    return Invoice(**base)


def test_next_period_revenue_with_no_shipment_is_not_a_cutoff_exception():
    inv = _inv(revenue_date=date(2027, 1, 15), shipped_date=None)
    assert revenue_cutoff([inv], PERIOD_END) == [], "下期收入不是本期截止例外"


def test_current_period_revenue_with_no_shipment_is_still_flagged():
    # 正对照：本期确认了收入却没有任何发货记录，必须报
    inv = _inv(revenue_date=date(2026, 9, 20), shipped_date=None)
    found = revenue_cutoff([inv], PERIOD_END)
    assert len(found) == 1
    assert found[0].severity == "high"
    assert "无发货" in found[0].detail


def test_ship_after_period_end_on_current_revenue_is_still_flagged():
    # 正对照：收入在本期、发货在下期 → 仍是截止例外
    inv = _inv(revenue_date=date(2026, 9, 28), shipped_date=date(2026, 10, 20))
    found = revenue_cutoff([inv], PERIOD_END)
    assert len(found) == 1
    assert "未发货却确认收入" in found[0].detail


def test_next_period_revenue_shipped_next_period_is_clean():
    inv = _inv(revenue_date=date(2027, 1, 15), shipped_date=date(2027, 1, 12))
    assert revenue_cutoff([inv], PERIOD_END) == []


def test_unrecognized_invoice_is_ignored():
    inv = _inv(revenue_date=None, shipped_date=None)
    assert revenue_cutoff([inv], PERIOD_END) == []
