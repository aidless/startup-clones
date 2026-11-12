import pytest

from cruxline import fixtures
from cruxline.judge import Judge
from cruxline.trace import Trace


@pytest.fixture(scope="module")
def verdicts():
    return {v.case_id: v for v in Judge(threshold=0.75).score_all(fixtures.TRACES)}


def test_good_traces_pass(verdicts):
    assert verdicts["c1"].passed and verdicts["c1"].score == pytest.approx(1.0)
    assert verdicts["c7"].passed


def test_no_tool_fails(verdicts):
    v = verdicts["c2"]
    assert not v.passed
    assert any(d.name == "uses_tool" and d.score == 0.0 for d in v.details)


def test_tool_error_and_refusal_fail(verdicts):
    assert not verdicts["c3"].passed
    assert any(d.name == "no_tool_error" and d.score == 0.0 for d in verdicts["c3"].details)
    assert not verdicts["c4"].passed
    assert any(d.name == "no_refusal" and d.score == 0.0 for d in verdicts["c4"].details)


def test_budget_and_terms(verdicts):
    assert any(d.name == "within_budget" and d.score == 0.0 for d in verdicts["c5"].details)
    assert any(d.name == "answers_expected_terms" and d.score < 1.0 for d in verdicts["c6"].details)
    assert not verdicts["c6"].passed


def test_judge_matches_expert_labels_except_none():
    """rubric 的判定应与专家标注一致（这是上线前提，不是巧合）。"""
    judge_map = {v.case_id: v.passed for v in Judge().score_all(fixtures.TRACES)}
    assert judge_map == fixtures.HUMAN_LABELS


def test_score_is_weighted_and_bounded():
    t = Trace(case_id="x", input="", output="退款成功", tool_calls=[])
    v = Judge().score(t)
    assert 0.0 <= v.score <= 1.0
    assert sum(d.weight for d in v.details) == pytest.approx(1.0)


def test_fatal_criterion_vetoes_even_with_high_score(verdicts):
    """致命项一票否决：c3 的期望要点全中（分数不低），但工具报错后编造必须判失败。"""
    v = verdicts["c3"]
    assert v.score >= 0.7
    assert not v.passed
    assert v.vetoed == ["no_tool_error"]
    assert "硬否决" in v.explain()
