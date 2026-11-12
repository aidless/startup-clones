"""编码 agent rubric：每条规则都要能被打红，也要能放行正常轨迹。

这些规则是从 60 条真实 dsh 会话轨迹里长出来的，不是拍脑袋写的：
「全程只用 bash」曾经被当成缺陷，实测发现那是正常编码行为（1829 次 bash vs 69 次 read），
所以换成了「改完不验证」。
"""

from cruxline.judge import Judge
from cruxline.rubrics import agent_rubric
from cruxline.trace import ToolCall, Trace


def call(name, args=None, result="", error=""):
    return ToolCall(name=name, args=args or {}, result=result, error=error)


def trace(calls, output="done", **meta):
    return Trace(case_id="c", input="q", output=output, tool_calls=calls, meta=meta)


def test_weights_sum_to_one_and_only_completion_is_fatal():
    rubric = agent_rubric()
    assert abs(sum(c.weight for c in rubric) - 1.0) < 1e-9
    assert [c.name for c in rubric if c.fatal] == ["turn_completed"]


def test_identical_retries_are_flagged():
    bad = trace([call("bash", {"command": "pytest"}) for _ in range(3)])
    score = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(bad).details}
    assert score["no_loop"] == 0.0

    ok = trace([call("bash", {"command": "pytest"}),
                call("bash", {"command": "pytest -x"}),
                call("bash", {"command": "pytest -x -q"})])
    score = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(ok).details}
    assert score["no_loop"] == 1.0


def test_retry_after_error_must_change_arguments():
    failed = call("bash", {"command": "make"}, error="exit code: 2")
    bad = trace([failed, call("bash", {"command": "make"}), call("bash", {"command": "ls"})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(bad).details}
    assert got["retry_after_error_changed"] == 0.0

    good = trace([failed, call("bash", {"command": "make -j1"})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(good).details}
    assert got["retry_after_error_changed"] == 1.0


def test_edit_requires_reading_the_file_first():
    path = "/tmp/a.py"
    bad = trace([call("edit", {"file_path": path})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(bad).details}
    assert got["read_before_write"] == 0.0

    good = trace([call("read", {"file_path": path}), call("edit", {"file_path": path})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(good).details}
    assert got["read_before_write"] == 1.0


def test_write_then_verify():
    path = "/tmp/b.py"
    bad = trace([call("read", {"file_path": path}), call("write", {"file_path": path})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(bad).details}
    assert got["verify_after_write"] == 0.0

    good = trace([call("read", {"file_path": path}), call("write", {"file_path": path}),
                  call("bash", {"command": "python -m pytest -q"})])
    got = {d.name: d.score for d in Judge(rubric=agent_rubric()).score(good).details}
    assert got["verify_after_write"] == 1.0


def test_interrupted_turn_is_not_an_agent_failure():
    """用户打断/压缩打断不是 agent 的错，只有 error 才否决。"""
    interrupted = trace([call("read", {"file_path": "/a"})], aborted=False, reason="interrupted")
    assert not Judge(rubric=agent_rubric()).score(interrupted).vetoed

    errored = trace([call("read", {"file_path": "/a"})], aborted=True, reason="error")
    verdict = Judge(rubric=agent_rubric()).score(errored)
    assert verdict.vetoed == ["turn_completed"]
    assert verdict.passed is False
