"""第三轮审查（docs/REVIEW-R3-audit-crux.md）cruxline 侧的复现测试。

覆盖 P0-2（calibrate 与 judge 用的不是同一把尺）、P0-3 + P1-6（README 的真实轨迹
数字与实测不符）、P1-4（`turn_completed` 只看 `aborted`）、P1-5（README 的 rubric 表
少一条、权重全错）、P2-5（`judge` 未文档化的落库副作用）。

共同的判据是**文档数字必须能由代码重算**：凡是 README 里印出来的结论，
这里都拿 `data/traces.jsonl` 现算一遍对上；凡是命令行报的口径，都用真子进程跑。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CRUXLINE_DIR = Path(__file__).resolve().parents[1]
README = (CRUXLINE_DIR / "README.md").read_text(encoding="utf-8")
DATA = CRUXLINE_DIR / "data" / "traces.jsonl"

from cruxline.cli import _read_traces  # noqa: E402
from cruxline.judge import DEFAULT_RUBRIC, Judge  # noqa: E402
from cruxline.rubrics import _turn_completed, agent_rubric  # noqa: E402
from cruxline.trace import Trace  # noqa: E402

THRESHOLD = 0.75

_HOW_TO_EXPORT = (
    "这批轨迹是 60 条真实 agent 会话（`~/.dsh/sessions` 导出，含生产内容，"
    "不随仓库发布）：`cd cruxline && python3 scripts/export_dsh_traces.py`；"
    "它只影响本文件里那些「拿真实语料现算」的用例，下面的纯逻辑用例照常跑")


def _needs_traces() -> None:
    """`data/traces.jsonl` 被 .gitignore 掉，且**没有**公网来源可补。"""
    if not DATA.exists():
        pytest.skip(f"缺少 {DATA}；{_HOW_TO_EXPORT}")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """真起子进程跑 CLI（不用 PYTHONPATH：工作区根名里的冒号会被当成路径分隔符）。"""
    code = ("import sys; sys.path.insert(0, {p!r});"
            "from cruxline.cli import main; sys.exit(main({a!r}))").format(
        p=str(CRUXLINE_DIR), a=list(args))
    return subprocess.run([sys.executable, "-c", code],
                          cwd=str(CRUXLINE_DIR), capture_output=True, text=True)


def _verdicts(rubric=None, traces=None):
    traces = traces if traces is not None else _read_traces(str(DATA))
    return Judge(rubric=rubric or agent_rubric(), threshold=THRESHOLD).score_all(traces)


# ---------------- P0-2：calibrate 必须与 judge 用同一把尺 ----------------

def _labels_file(tmp_path: Path) -> Path:
    """30 条人工标注：前 20 条判 PASS、后 10 条判 FAIL（两栏都有，kappa 可算）。"""
    traces = _read_traces(str(DATA))[:30]
    labels = {t.case_id: i < 20 for i, t in enumerate(traces)}
    p = tmp_path / "expert.json"
    p.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return p


def test_calibrate_defaults_to_agent_rubric(tmp_path):
    """`judge` 默认 agent，`calibrate` 却写死 `Judge(threshold=...)`=DEFAULT_RUBRIC。
    校准的是另一把尺，于是「rubric 差异」被误诊成「judge 偏松/偏严」。"""
    _needs_traces()
    labels = _labels_file(tmp_path)
    proc = run_cli("calibrate", "--traces", str(DATA), "--labels", str(labels))
    out = proc.stdout
    assert "rubric=agent" in out, f"calibrate 没说自己用的是哪套 rubric：\n{out}"

    traces = _read_traces(str(DATA))[:30]
    expected = sum(v.passed for v in _verdicts(agent_rubric(), traces)) / len(traces)
    assert f"judge 通过率 {expected:.1%}" in out, \
        f"calibrate 的 judge 通过率 {out}\n ≠ agent rubric 实测 {expected:.1%}"


def test_calibrate_can_select_default_rubric(tmp_path):
    """显式 `--rubric default` 必须换尺（并且说清楚换成了哪把）。"""
    _needs_traces()
    labels = _labels_file(tmp_path)
    proc = run_cli("calibrate", "--traces", str(DATA), "--labels", str(labels),
                   "--rubric", "default")
    out = proc.stdout
    assert "rubric=default" in out
    traces = _read_traces(str(DATA))[:30]
    expected = sum(v.passed for v in _verdicts(DEFAULT_RUBRIC, traces)) / len(traces)
    assert f"judge 通过率 {expected:.1%}" in out


def test_calibrate_rejects_unknown_rubric(tmp_path):
    _needs_traces()
    labels = _labels_file(tmp_path)
    proc = run_cli("calibrate", "--traces", str(DATA), "--labels", str(labels),
                   "--rubric", "nope")
    assert proc.returncode != 0
    assert "invalid choice" in proc.stderr


# ---------------- P1-4：turn_completed 的判据 ----------------

@pytest.mark.parametrize("meta", [{"reason": "error"}, {"aborted": True},
                                  {"reason": "error", "aborted": True}])
def test_turn_completed_fails_on_error(meta):
    """README 说「只有 `error` 才硬否决」，代码却只看 `aborted` 布尔：
    一条 `reason=error` 但没有 `aborted` 的轨迹拿满 0.15 分，还打印
    「结束原因 error」——读日志的人以为它被抓了，实际一分没扣。"""
    score, note = _turn_completed(Trace("x", "i", "o", [], meta))
    assert score == 0.0
    assert "error" in note or "aborted" in note


@pytest.mark.parametrize("meta", [{}, {"reason": "completed"}, {"reason": "interrupted"}])
def test_turn_completed_passes_on_normal_end(meta):
    # 正对照：interrupted 是用户/压缩打断，不是 agent 的错（README 明写）
    score, _ = _turn_completed(Trace("x", "i", "o", [], meta))
    assert score == 1.0


def test_trace_from_dict_reconciles_aborted_and_reason():
    """同一事实不许有两个真相：导出器只给一个字段时，规范化阶段补齐另一个。"""
    t = Trace.from_dict({"case_id": "a", "meta": {"reason": "error"}})
    assert t.meta["aborted"] is True

    t2 = Trace.from_dict({"case_id": "b", "meta": {"aborted": True}})
    assert t2.meta["reason"] == "aborted"

    t3 = Trace.from_dict({"case_id": "c", "meta": {}})
    assert t3.meta.get("aborted") is False
    assert t3.meta.get("reason") == "completed"


def test_error_trace_in_real_corpus_is_not_scored_as_completed():
    """真实语料里确实有 reason=error 的轨迹：修完之后它必须拿 0 分。"""
    _needs_traces()
    traces = _read_traces(str(DATA))
    errored = [t for t in traces if t.meta.get("reason") == "error"]
    assert errored, "语料里应当有 reason=error 的轨迹"
    assert all(_turn_completed(t)[0] == 0.0 for t in errored)


# ---------------- P1-5：README 的 rubric 表 = 代码 ----------------

def _rubric_rows_from_readme() -> list[tuple[str, str, str]]:
    """按单元格解析 rubric 表：空单元格与 ✅ 都要能吃，别用对空白敏感的正则。"""
    rows = []
    for line in README.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[1].replace(".", "", 1).isdigit():
            continue
        rows.append((cells[0].strip("`"), format(float(cells[1]), ".2f"),
                     "✅" if cells[2] == "✅" else ""))
    return rows


def test_readme_rubric_table_matches_code():
    rows = _rubric_rows_from_readme()
    code = [(c.name, format(c.weight, ".2f"), "✅" if c.fatal else "")
            for c in agent_rubric()]
    assert rows == code, f"README 表与代码不一致\nREADME={rows}\n代码={code}"
    assert abs(sum(c.weight for c in agent_rubric()) - 1.0) < 1e-9


def test_readme_does_not_claim_a_single_fatal_item():
    assert "只有一条致命项" not in README
    fatal = [c.name for c in agent_rubric() if c.fatal]
    assert len(fatal) == 2
    for name in fatal:
        assert f"`{name}`" in README


# ---------------- P0-3 / P1-6：README 的真实轨迹数字 ----------------

def test_readme_headline_matches_recomputed_counts():
    _needs_traces()
    vs = _verdicts()
    passed = sum(v.passed for v in vs)
    assert (len(vs), passed) == (60, 59), "语料或判据变过，先确认基线再改 README"
    assert f"PASS {passed} / FAIL {len(vs) - passed}" in README


def test_readme_t141_line_matches_real_verdict():
    """README 拿 `#t141` 当「规则真能抓缺陷」的唯一样本，实测它是 0.800 PASS。
    文档不许为了自圆其说去改 rubric 阈值 —— 只许把真相写对。"""
    _needs_traces()
    vs = _verdicts()
    v = next(v for v in vs if v.case_id.endswith("#t141"))
    line = next(ln for ln in README.splitlines() if "#t141" in ln)
    assert f"{v.score:.3f}" in line, f"README 写死的分数与实测 {v.score:.3f} 不符：{line}"
    assert ("PASS" if v.passed else "FAIL") in line


def test_readme_fail_case_is_a_real_fail():
    """改成「真命中」时，被举的那条必须真的 FAIL（举一条 PASS 当反例 = 自相矛盾）。"""
    _needs_traces()
    failed = [v for v in _verdicts() if not v.passed]
    assert failed, "语料里应有 FAIL 样本"
    for v in failed:
        assert v.case_id in README, f"README 没有引用真实 FAIL 样本 {v.case_id}"


# ---------------- P2-5：judge 的落库副作用要写在文档里 ----------------

def test_readme_documents_judge_db_side_effect():
    assert "cruxline.db" in README
    assert "--db" in README
