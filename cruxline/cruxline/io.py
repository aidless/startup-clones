"""通用轨迹适配器：把别人家的轨迹读成 `Trace`。

自己攒的轨迹长得都不太一样：OpenAI 的 eval 导出用 `id/question/answer/steps`，
通用回放器写 `trace_id/prompt/response/actions`，本仓库的 `Trace.from_dict`
只认 `case_id/input/output/tool_calls`。适配层只做三件事：

1. 认容器：`.jsonl`（一行一条）与 `.json`（顶层数组）都吃，空文件返回 `[]`；
2. 认字段：常见别名逐个映射到 `Trace` / `ToolCall`；
3. 认不出来就报错，并且报得能直接改：第几条 + 它有哪些键。
   静默丢记录是最坏的失败——用户会以为判了 60 条，实际只判了 40 条。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .trace import ToolCall, Trace

# 轨迹 id：本仓库 / OpenAI eval / JS 驼峰 / 通用回放器
ID_KEYS = ("case_id", "id", "caseId", "trace_id")
INPUT_KEYS = ("input", "question", "prompt", "user_input")
OUTPUT_KEYS = ("output", "answer", "response", "final_output")
TOOL_CALL_KEYS = ("tool_calls", "toolCalls", "steps", "actions")

# 单次调用：工具名 / 参数 / 结果 / 错误
NAME_KEYS = ("name", "tool", "tool_name")
ARGS_KEYS = ("args", "arguments", "input")
RESULT_KEYS = ("result", "output", "observation")
ERROR_TEXT_KEYS = ("error", "error_message")

# `is_error: true` 但导出器没给错误文本时写这个，别写成空串装作没报错
UNKNOWN_ERROR = "(unknown error)"

_FALSE_STRINGS = {"", "false", "0", "no", "none", "null"}


def _first(d: Mapping[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _as_args(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"raw": value}
        if isinstance(parsed, Mapping):
            return dict(parsed)
        return {"raw": value}
    return {}


def _error_text(d: Mapping[str, Any]) -> str:
    """错误列的三种写法：文本（error/error_message）与布尔开关（is_error）。"""
    text = _as_text(_first(d, ERROR_TEXT_KEYS))
    flag = d.get("is_error")
    if isinstance(flag, str) and flag.strip().lower() not in _FALSE_STRINGS:
        # `is_error` 被塞了错误文本的导出器
        return text or flag
    if not text and bool(flag):
        return UNKNOWN_ERROR
    return text


def _to_tool_call(raw: Any, index: int) -> ToolCall:
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"第 {index} 条轨迹的工具调用不是对象（{type(raw).__name__}）：{raw!r}")
    name = _first(raw, NAME_KEYS)
    if not name:
        raise ValueError(
            f"第 {index} 条轨迹的工具调用缺少工具名（可用别名 "
            f"{'/'.join(NAME_KEYS)}），它有哪些键：{sorted(raw)}")
    return ToolCall(
        name=str(name),
        args=_as_args(_first(raw, ARGS_KEYS, {})),
        result=_as_text(_first(raw, RESULT_KEYS)),
        error=_error_text(raw),
    )


def _to_trace(raw: Any, index: int) -> Trace:
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"第 {index} 条轨迹不是对象（{type(raw).__name__}），无法识别：{raw!r}")

    keys = sorted(str(k) for k in raw)
    case_id = _first(raw, ID_KEYS)
    if case_id is None or case_id == "":
        raise ValueError(
            f"第 {index} 条轨迹缺少 id（可用别名 {'/'.join(ID_KEYS)}），"
            f"它有哪些键：{keys}")
    if not any(k in raw for k in INPUT_KEYS + OUTPUT_KEYS + TOOL_CALL_KEYS):
        raise ValueError(
            f"第 {index} 条轨迹没有输入/输出/工具调用（可用别名 "
            f"{'/'.join(INPUT_KEYS)}、{'/'.join(OUTPUT_KEYS)}、"
            f"{'/'.join(TOOL_CALL_KEYS)}），它有哪些键：{keys}")

    raw_calls = _first(raw, TOOL_CALL_KEYS, [])
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, (list, tuple)):
        raise ValueError(
            f"第 {index} 条轨迹的 {TOOL_CALL_KEYS[0]} 必须是数组，"
            f"实际是 {type(raw_calls).__name__}；它有哪些键：{keys}")

    meta = dict(raw.get("meta") or {})
    # 走 Trace.from_dict 统一补 meta（reason/aborted 的两种写法只在那一处收口）
    return Trace.from_dict({
        "case_id": str(case_id),
        "input": _as_text(_first(raw, INPUT_KEYS)),
        "output": _as_text(_first(raw, OUTPUT_KEYS)),
        "tool_calls": [_to_tool_call(c, index) for c in raw_calls],
        "meta": meta,
    })


def _parse_jsonl(text: str) -> list[Any]:
    items: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {lineno} 行不是合法 JSON：{exc}") from exc
    return items


def read_traces(path: str | Path) -> list[Trace]:
    """读轨迹文件 → `list[Trace]`。

    - `.jsonl`：一行一条，空行跳过；
    - `.json`：顶层数组；单个对象也接受（导出器常只写一条）；
    - 空文件：`[]`，由调用方决定「没有轨迹」算不算失败（`judge` 会报错）。
    """
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []

    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        items = _parse_jsonl(text)
    else:
        if isinstance(whole, list):
            items = whole
        elif isinstance(whole, Mapping):
            items = [whole]
        else:
            raise ValueError(
                f"轨迹文件顶层必须是数组或对象，实际是 {type(whole).__name__}")

    return [_to_trace(raw, i) for i, raw in enumerate(items, 1)]


__all__ = ["read_traces"]
