"""借用外部机制的回归测试（来源见 docs/BORROWED.md）。

B-1 Wilson 区间：来自 Inspect（inspect.aisi.org.uk/metrics.html）的 ci_wilson()。
    60 条用例 59 过 = 98.3%，裸数字会让客户以为「几乎全过」；
    区间下界 91.1% 才是他能拿去跟老板说的话。
B-2 用例集指纹：来自 Inspect 的 eval-set 稳定 sample id —— 只报通过率不报
    「这次量的是哪一批用例」，换一批用例也能印出「涨了」。
"""
from __future__ import annotations

import pytest

from cruxline.regress import diff
from cruxline.stats import set_fingerprint, wilson_interval


def test_wilson_matches_reference_value():
    lo, hi = wilson_interval(59, 60)
    assert lo == pytest.approx(0.9115, abs=1e-3)
    assert hi == pytest.approx(0.9971, abs=1e-3)


def test_wilson_bounds_stay_inside_unit_interval_at_extremes():
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.35          # 0/10 不是「0% 确定」，上界近 30%
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.75


def test_wilson_widens_as_sample_shrinks():
    narrow = wilson_interval(30, 60)
    wide = wilson_interval(3, 6)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_wilson_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson_interval(5, 3)
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_fingerprint_ignores_order_but_tracks_membership():
    a = set_fingerprint(["t2", "t1", "t3"])
    b = set_fingerprint(["t3", "t1", "t2"])
    c = set_fingerprint(["t1", "t2", "t4"])
    assert a == b and len(a) == 12
    assert a != c


def test_report_carries_rate_interval_and_case_set_fingerprint():
    base = {"t1": True, "t2": True, "t3": False, "t4": False}
    cur = {"t1": True, "t2": True, "t3": True, "t4": True}
    rep = diff(base, cur)
    md = rep.to_markdown()
    assert rep.n == 4
    assert rep.fingerprint == set_fingerprint(base)
    assert "95% CI" in md, md
    assert rep.fingerprint in md, md
