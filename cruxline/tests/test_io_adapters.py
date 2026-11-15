"""通用轨迹适配器：别人家的轨迹必须能被原样读进来。

判据一律是「真实文件 → 真实 Trace 对象 / 真实 CLI 输出」，不 mock 读取层：
- 两种容器格式（`.jsonl` 一行一条 / `.json` 顶层数组）；
- 三类导出器字段别名（本仓库 / OpenAI eval 风格 / 通用 trace_id 风格）；
- 认不出来的记录必须报错并指出**第几条**与**它有哪些键**（否则用户不知道改哪里）；
- 空文件是合法输入，返回 `[]`（「没有轨迹」由 judge 自己报）。
"""
from __future__ import annotations

import json

import pytest

from cruxline.io import read_traces
from cruxline.trace import Trace


def _write(path, text: str):
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_jsonl_one_record_per_line(tmp_path):
    p = _write(tmp_path / "t.jsonl", "\n".join([
        json.dumps({"case_id": "a1", "input": "q1", "output": "o1"}),
        json.dumps({"case_id": "a2", "input": "q2", "output": "o2"}),
    ]) + "\n")
    traces = read_traces(str(p))
    assert [t.case_id for t in traces] == ["a1", "a2"]
    assert [t.output for t in traces] == ["o1", "o2"]
    assert all(isinstance(t, Trace) for t in traces)


def test_reads_json_top_level_array(tmp_path):
    p = _write(tmp_path / "t.json", json.dumps([
        {"case_id": "b1", "input": "q", "output": "a"},
        {"case_id": "b2", "input": "q", "output": "a"},
        {"case_id": "b3", "input": "q", "output": "a"},
    ]))
    assert [t.case_id for t in read_traces(str(p))] == ["b1", "b2", "b3"]


def test_openai_style_aliases_are_mapped(tmp_path):
    """id/question/answer 这套别名来自 OpenAI 的 eval 导出。"""
    p = _write(tmp_path / "t.jsonl", json.dumps({
        "id": "openai-1",
        "question": "北京的首都是哪里？",
        "answer": "北京",
    }) + "\n")
    t = read_traces(str(p))[0]
    assert (t.case_id, t.input, t.output) == ("openai-1", "北京的首都是哪里？", "北京")


def test_other_id_and_text_aliases_are_mapped(tmp_path):
    """caseId / trace_id、prompt / user_input、response / final_output 都要能认。"""
    p = _write(tmp_path / "t.json", json.dumps([
        {"caseId": "c1", "prompt": "p1", "response": "r1"},
        {"trace_id": "c2", "user_input": "p2", "final_output": "r2"},
    ]))
    got = [(t.case_id, t.input, t.output) for t in read_traces(str(p))]
    assert got == [("c1", "p1", "r1"), ("c2", "p2", "r2")]


def test_nested_steps_are_mapped_to_tool_calls(tmp_path):
    """`steps` / `actions` 里的 tool / arguments / observation 是另一套嵌套结构。"""
    p = _write(tmp_path / "t.jsonl", json.dumps({
        "id": "s1",
        "question": "查一下磁盘",
        "answer": "已查",
        "steps": [
            {"tool": "bash", "arguments": {"command": "df -h"}, "observation": "80% used"},
            {"tool_name": "read", "args": {"path": "/etc/hosts"}, "result": "127.0.0.1"},
        ],
    }) + "\n")
    calls = read_traces(str(p))[0].tool_calls
    assert [(c.name, c.args, c.result) for c in calls] == [
        ("bash", {"command": "df -h"}, "80% used"),
        ("read", {"path": "/etc/hosts"}, "127.0.0.1"),
    ]
    assert [c.error for c in calls] == ["", ""]


def test_is_error_true_maps_to_a_non_empty_error(tmp_path):
    """`is_error: true` 只有布尔没有文本时，必须落成可见的错误串而不是空。"""
    p = _write(tmp_path / "t.jsonl", json.dumps({
        "id": "e1", "question": "q", "answer": "a",
        "steps": [
            {"tool": "write_file", "arguments": {}, "observation": "", "is_error": True},
            {"tool": "export", "arguments": {}, "is_error": True, "error_message": "disk full"},
            {"tool": "read", "arguments": {}, "observation": "ok", "is_error": False},
        ],
    }) + "\n")
    calls = read_traces(str(p))[0].tool_calls
    assert calls[0].error == "(unknown error)"
    assert calls[1].error == "disk full"
    assert calls[2].error == ""
    # 反过来读：布尔 true 转成的错误必须被 Trace.has_error 看见
    assert read_traces(str(p))[0].has_error is True


def test_unrecognized_record_reports_index_and_its_keys(tmp_path):
    """报错消息要能直接告诉用户改第几条、那条有哪些键。"""
    p = _write(tmp_path / "t.jsonl", "\n".join([
        json.dumps({"id": "ok-1", "question": "q", "answer": "a"}),
        json.dumps({"foo": 1, "bar": 2}),
    ]) + "\n")
    with pytest.raises(ValueError) as ei:
        read_traces(str(p))
    msg = str(ei.value)
    assert "第 2 条" in msg
    assert "foo" in msg and "bar" in msg


def test_empty_file_returns_empty_list(tmp_path):
    """空文件不是错误：judge 自己会说「没有轨迹」。"""
    p = _write(tmp_path / "empty.jsonl", "\n\n   \n")
    assert read_traces(str(p)) == []


def test_cli_judge_runs_end_to_end_on_adapted_traces(tmp_path, capsys):
    """适配后的轨迹必须能直接跑通 CLI，并算出真实通过率。"""
    from cruxline.cli import main

    p = _write(tmp_path / "openai.jsonl", "\n".join([
        # 通过：工具无报错、有结尾答复
        json.dumps({"id": "pass-1", "question": "q", "answer": "完成",
                    "steps": [{"tool": "read", "arguments": {"path": "a.py"},
                               "observation": "ok"}]}),
        # 否决：工具报错却继续宣布成功
        json.dumps({"id": "fail-1", "question": "q", "answer": "全部推送成功",
                    "steps": [{"tool": "push", "arguments": {}, "is_error": True}]}),
    ]) + "\n")

    code = main(["judge", "--traces", str(p), "--json", "--db", str(tmp_path / "c.db")])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["total"] == 2
    assert payload["passed"] == 1
    assert payload["pass_rate"] == 0.5
    assert [v["case_id"] for v in payload["verdicts"]] == ["pass-1", "fail-1"]
