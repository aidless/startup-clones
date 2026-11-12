import pytest

from filinglens import facts as F
from filinglens.fixtures import FAKE_FACTS


@pytest.fixture
def conn():
    return F.load_companyfacts(FAKE_FACTS, ":memory:")


def test_only_annual_10k_rows_loaded(conn):
    n = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert n == 12  # 4 指标 × 3 年


def test_resolve_metric_english_and_chinese():
    assert F.resolve_metric("what was total revenue in fiscal 2025")[1] == "revenue"
    assert F.resolve_metric("研发投入占比")[1] == "研发"
    assert F.resolve_metric("how many employees") is None


def test_annual_series_and_yoy(conn):
    series = F.annual_series(conn, "revenue")
    assert [f.fy for f in series] == [2023, 2024, 2025]
    assert [f.val for f in series] == [100_000_000, 130_000_000, 175_000_000]
    changes = dict(F.yoy(series))
    assert changes[2024] == pytest.approx(0.30, abs=1e-4)
    assert changes[2025] == pytest.approx(0.3462, abs=1e-3)


def test_fmt_money():
    assert F.fmt_money(175_000_000) == "175.0M USD"
    assert F.fmt_money(1_200_000_000) == "1.20B USD"
    assert F.fmt_money(900) == "900 USD"


def test_missing_tag_returns_empty(conn):
    assert F.annual_series(conn, "inventory") == []
