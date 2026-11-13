"""审查报告 P1（cruxline）五条的复现测试（2026-11-12 审查）。

五条的共同点：判据看着在跑，实际上对真实轨迹失效 ——
签名受 dict 键序影响、错误识别只认两种字面、bash 写盘隐形、
kappa 在退化分布上返 1.0、标注主键秒级精度覆盖历史。
"""
from __future__ import annotations

import json

import pytest

from cruxline import store
from cruxline.calib import calibrate, cohen_kappa
from cruxline.rubrics import _signature
from cruxline.trace import ToolCall, Trace


def _tc(name, args, error=""):
    return ToolCall(name=name, args=args, error=error)


def _trace(calls):
    return Trace(case_id="t", input="", output="done", tool_calls=calls)


# ---------------- P1-a 签名与键序无关 ----------------

def test_signature_ignores_dict_key_order():
    a = _tc("read", {"file_path": "x.py", "offset": 1, "limit": 20})
    b = _tc("read", {"limit": 20, "offset": 1, "file_path": "x.py"})
    assert _signature(a) == _signature(b)


# ---------------- P1-b 错误识别覆盖真实报错 ----------------

@pytest.mark.parametrize("body", [
    "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom",
    "bash: foo: command not found",
    "cat: /nope: No such file or directory",
    "exit code: 2",
    "Error: permission denied",
    "npm ERR! code ELIFECYCLE",
])
def test_classify_error_recognises_real_failures(body):
    from scripts.export_dsh_traces import classify_error

    assert classify_error(body) != "", f"应识别为错误：{body[:40]!r}"


@pytest.mark.parametrize("body", [
    "exit code: 0\nall good",
    "Success. 12 files changed",
    "error: 0 warnings",  # 计数式表述，不是失败
])
def test_classify_error_does_not_flag_success(body):
    from scripts.export_dsh_traces import classify_error

    assert classify_error(body) == ""


# ---------------- P1-c bash 写盘也算写 ----------------

def test_read_before_write_sees_bash_inplace_edit():
    """真实轨迹里改文件常走 bash：sed -i、tee -a、>> 追加到 .py。
    原文只认 write/edit/multiedit，这类原地修改完全隐形。"""
    from cruxline.rubrics import _read_before_write

    for cmd in ("sed -i 's/1/2/' src/app.py",
                "tee -a src/app.py <<'EOF'\nprint(1)\nEOF",
                "echo 'x = 1' >> src/app.py"):
        t = _trace([_tc("bash", {"command": cmd})])
        score, reason = _read_before_write(t)
        assert score == 0.0, f"{cmd} 应判未读就改：{reason}"
        assert "app.py" in reason


def test_read_before_bash_inplace_edit_is_clean():
    from cruxline.rubrics import _read_before_write

    t = _trace([
        _tc("read", {"file_path": "src/app.py"}),
        _tc("bash", {"command": "sed -i 's/1/2/' src/app.py"}),
    ])
    assert _read_before_write(t)[0] == 1.0


def test_bash_heredoc_creating_new_file_is_not_penalised():
    """假阳守卫：`cat > new.py <<EOF` 无法从轨迹区分「新建」与「覆盖」——
    新建本来就不需要先读。宁可漏判这一种，也不能把「生成文件」全判成违规。"""
    from cruxline.rubrics import _read_before_write

    t = _trace([_tc("bash", {"command": "cat > src/new_file.py <<'EOF'\nprint(1)\nEOF"})])
    assert _read_before_write(t)[0] == 1.0


def test_bash_append_to_report_md_is_not_penalised():
    """假阳守卫：往报告 .md 里追加内容是生成产物，不是原地改代码。"""
    from cruxline.rubrics import _read_before_write

    t = _trace([_tc("bash", {"command": "echo '## 结果' >> reports/RESULT_20261113.md"})])
    assert _read_before_write(t)[0] == 1.0


def test_bash_log_redirect_is_not_a_code_write():
    """假阳守卫：`> run.log 2>&1`、`2>/dev/null` 不是写代码文件。"""
    from cruxline.rubrics import _read_before_write

    t = _trace([_tc("bash", {"command": "python train.py > run.log 2>/dev/null"})])
    assert _read_before_write(t)[0] == 1.0


def test_bash_without_redirect_is_not_a_write():
    from cruxline.rubrics import _read_before_write

    t = _trace([_tc("bash", {"command": "pytest -q"})])
    assert _read_before_write(t)[0] == 1.0


# ---------------- P1-d 退化分布上的 kappa ----------------

def test_kappa_of_constant_rater_is_not_one():
    """恒定判 PASS 的裁判在 5 条全 PASS 上：pe == 1，kappa 是 0/0。
    原文返回 1.0 并判「达标」——一个什么都没测的裁判拿到了合格证。"""
    all_pass = [True] * 5
    assert cohen_kappa(all_pass, all_pass) != 1.0


def test_n_equals_one_is_not_ok():
    cal = calibrate({"c1": True}, {"c1": True})
    assert cal.ok is False
    assert cal.degenerate is True


def test_constant_rater_calibration_is_not_ok():
    human = {f"c{i}": True for i in range(5)}
    judge = {f"c{i}": True for i in range(5)}
    cal = calibrate(human, judge)
    assert cal.ok is False
    assert "退化" in cal.diagnosis or "无判别力" in cal.diagnosis


def test_normal_calibration_still_ok():
    # 正对照：有分歧、n 足够、kappa 达标 → 必须放行
    human = {"a": True, "b": True, "c": False, "d": False, "e": True, "f": False}
    judge = {"a": True, "b": False, "c": False, "d": False, "e": True, "f": True}
    cal = calibrate(human, judge, min_kappa=0.2)
    assert cal.ok is True
    assert cal.degenerate is False


# ---------------- P1-e 标注不可被同秒覆盖 ----------------

def test_two_labels_in_same_second_are_both_kept():
    conn = store.connect()
    store.add_label(conn, "case-1", "alice", True, rationale="first")
    store.add_label(conn, "case-1", "alice", False, rationale="second")
    rows = conn.execute(
        "SELECT passed, rationale FROM labels WHERE case_id='case-1' ORDER BY created_at"
    ).fetchall()
    assert len(rows) == 2, f"应保留两条历史，实际 {rows}"
    assert store.load_labels(conn, "alice")["case-1"] is False  # 取最新


def test_exact_duplicate_label_row_not_duplicated():
    conn = store.connect()
    store.add_label(conn, "case-1", "alice", True, rationale="same")
    store.add_label(conn, "case-1", "alice", True, rationale="same")
    n = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    assert n <= 2, "同内容重复行可以合，但不能凭空增殖"
