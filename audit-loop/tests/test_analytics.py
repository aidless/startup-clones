from auditloop.analytics import Series, cash_conversion, gross_margin_trend, revenue_vs_receivables, run_all


def test_receivable_divergence_is_flagged():
    """收入平、应收暴涨 —— 必须报。"""
    s = Series(revenue={2024: 1000.0, 2025: 1050.0},
               receivables={2024: 100.0, 2025: 145.0})
    f = revenue_vs_receivables(s)
    assert len(f) == 1
    assert f[0].ref == "FY2025"
    assert f[0].assertion == "存在性"
    assert f[0].severity == "medium"          # +45% - +5% = 40pt，未到 2 倍阈值
    assert "应收账款增速 +45.0%" in f[0].detail


def test_normal_growth_is_not_flagged():
    """收入与应收同步增长不该报（避免制造假例外）。"""
    s = Series(revenue={2024: 1000.0, 2025: 1100.0},
               receivables={2024: 100.0, 2025: 110.0})
    assert revenue_vs_receivables(s) == []


def test_margin_shift_and_cash_conversion():
    s = Series(revenue={2024: 1000.0, 2025: 1000.0},
               gross_profit={2024: 400.0, 2025: 460.0},
               cfo={2024: 250.0, 2025: 180.0})
    m = gross_margin_trend(s)
    assert len(m) == 1 and "40.0%" in m[0].detail and "46.0%" in m[0].detail
    c = cash_conversion(s)
    assert len(c) == 1 and "0.25" in c[0].detail and "0.18" in c[0].detail
    assert {f.check for f in run_all(s)} == {
        "analytics.gross_margin_trend", "analytics.cash_conversion"}


def test_missing_series_yields_nothing_instead_of_guessing():
    assert revenue_vs_receivables(Series(revenue={2024: 1.0, 2025: 2.0})) == []
    assert run_all(Series(revenue={2024: 1.0, 2025: 2.0})) == []
