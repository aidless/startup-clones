import pytest

from cruxline import fixtures
from cruxline.calib import calibrate, cohen_kappa
from cruxline.judge import Judge
from cruxline.regress import diff
from cruxline.store import add_label, connect, latest_verdicts, load_labels

# 手算基准：po=0.8, pe=0.5 → kappa=0.6
A = [True, True, True, True, True, False, False, False, False, False]
B = [True, True, True, True, False, False, False, False, False, True]


def test_kappa_hand_computed():
    assert cohen_kappa(A, B) == pytest.approx(0.6)


def test_kappa_identical_is_one():
    assert cohen_kappa(A, A) == 1.0


def test_kappa_inverted_is_negative():
    assert cohen_kappa(A, [not x for x in A]) < 0


def test_kappa_rejects_mismatched_length():
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_calibration_gate_blocks_inverted_judge():
    human = fixtures.HUMAN_LABELS
    inverted = {k: not v for k, v in human.items()}
    cal = calibrate(human, inverted, min_kappa=0.6)
    assert not cal.ok
    assert cal.kappa < 0
    assert "方向写反" in cal.diagnosis


def test_calibration_passes_on_agreeing_judge():
    human = fixtures.HUMAN_LABELS
    judge_map = {v.case_id: v.passed for v in Judge().score_all(fixtures.TRACES)}
    cal = calibrate(human, judge_map, min_kappa=0.6)
    assert cal.ok and cal.kappa == 1.0


def test_regress_identifies_regression_and_fix():
    rep = diff(fixtures.HUMAN_LABELS, fixtures.second_run_labels())
    assert rep.regressions == ["c1"]
    assert rep.fixes == ["c2", "c6"]
    assert rep.verdict == "review"
    assert rep.before_rate == pytest.approx(0.25)
    assert rep.after_rate == pytest.approx(0.375)


def test_regress_blocks_when_net_zero_with_regression():
    rep = diff({"a": True, "b": False}, {"a": False, "b": True})
    assert rep.delta == 0.0 and rep.regressions == ["a"]
    assert rep.verdict == "block"


def test_label_store_keeps_human_and_judge_separate():
    conn = connect(":memory:")
    add_label(conn, "c1", "expert", True, rationale="主管")
    latest_verdicts(conn, Judge().score_all(fixtures.TRACES))
    expert = load_labels(conn, "expert")
    judge = load_labels(conn, "judge")
    assert expert == {"c1": True}
    assert len(judge) == len(fixtures.TRACES)
