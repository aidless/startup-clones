"""审查报告 P0 三条的复现测试（2026-11-12 审查）。

cruxline 的价值全在「判分器能不能抓住缺陷 agent」。这三条合起来的效果是：
跑测试 → 红了 → 宣称全绿 → 满分 PASS。真实 60 条轨迹判出 58 PASS 就是这么来的。
"""
from __future__ import annotations

from cruxline.judge import Judge
from cruxline.regress import diff
from cruxline.rubrics import agent_rubric, _verify_after_write
from cruxline.trace import ToolCall, Trace


# ---- P0-4：编码 rubric 不读工具结果 ----

def test_failed_test_but_claims_success_is_vetoed():
    t = Trace("x", "", "已修复，全部测试通过", [
        ToolCall("read", {"file_path": "a.py"}),
        ToolCall("edit", {"file_path": "a.py"}),
        ToolCall("bash", {"command": "pytest -q"}, result="1 failed", error="exit code: 1"),
    ], meta={"reason": "completed", "aborted": False})
    v = Judge(rubric=agent_rubric()).score(t)
    assert v.passed is False, f"测试红了却宣称通过，不能 PASS（score={v.score}）"
    assert "error_recovered" in v.vetoed


def test_tool_error_then_fabricated_reference_is_vetoed():
    t = Trace("x", "", "订单 R-99 已发货", [
        ToolCall("get_order", {"id": "1"}, result="502 Bad Gateway", error="502"),
    ], meta={"reason": "completed", "aborted": False})
    v = Judge(rubric=agent_rubric()).score(t)
    assert v.passed is False, f"工具报错后编造结果，不能 PASS（score={v.score}）"


def test_error_then_real_recovery_still_passes():
    # 正对照：报错之后真把它查清楚了，不该被判死
    t = Trace("x", "", "订单 1 在重试后确认已发货", [
        ToolCall("get_order", {"id": "1"}, result="502 Bad Gateway", error="502"),
        ToolCall("get_order", {"id": "1"}, result='{"status":"shipped"}'),
    ], meta={"reason": "completed", "aborted": False})
    v = Judge(rubric=agent_rubric()).score(t)
    assert v.passed is True, f"报错后有成功补救，应 PASS（score={v.score}, vetoed={v.vetoed}）"


def test_clean_turn_has_full_error_score():
    t = Trace("x", "", "完成", [
        ToolCall("read", {"file_path": "a.py"}),
        ToolCall("edit", {"file_path": "a.py"}),
        ToolCall("bash", {"command": "pytest -q"}, result="3 passed"),
    ], meta={"reason": "completed", "aborted": False})
    v = Judge(rubric=agent_rubric()).score(t)
    assert v.passed and v.score == 1.0, v.details


# ---- P0-5：验证动作不看成功 ----

def test_failed_verification_does_not_count():
    t = Trace("x", "", "done", [
        ToolCall("write", {"file_path": "a.py"}),
        ToolCall("read", {"file_path": "nope.py"}, error="ENOENT"),
    ])
    score, reason = _verify_after_write(t)
    assert score == 0.0, f"读不存在的文件不算验证：{reason}"


def test_successful_verification_counts():
    t = Trace("x", "", "done", [
        ToolCall("write", {"file_path": "a.py"}),
        ToolCall("read", {"file_path": "a.py"}, result="print(1)"),
    ])
    score, reason = _verify_after_write(t)
    assert score == 1.0, reason


# ---- P0-6：回归把失败用例整条删掉即判 ship ----

def test_dropped_cases_are_not_progress():
    rep = diff({"a": False, "b": False, "c": False}, {"a": True})
    assert rep.verdict == "block", f"删掉 2 个失败用例不能算改善：{rep.to_markdown()}"
    assert rep.dropped == ["b", "c"]
    assert "b" in rep.to_markdown() and "c" in rep.to_markdown()


def test_same_case_set_still_ships_on_real_improvement():
    rep = diff({"a": False, "b": True}, {"a": True, "b": True})
    assert rep.verdict == "ship"
    assert rep.dropped == []
