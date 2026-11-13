"""两套 rubric：一套给客服/工单类 agent（手工夹具），一套给编码 agent（真实会话轨迹）。

为什么要分开：客服场景里「工具报错」是硬否决；编码场景里报错是常态
（grep 没匹配、编译失败、测试红），真正的失败信号是「报错后原封不动重试」和
「没读过就改文件」。用同一套权重评两类任务，等于拿体温计量血压。
"""

from __future__ import annotations

from collections import Counter

from .judge import (
    DEFAULT_RUBRIC,
    Criterion,
    _answers_expected_terms,
    _no_refusal,
    _no_tool_error,
    _uses_tool,
    _within_budget,
)
import re

from .trace import Trace

REPEAT_LIMIT = 3          # 同一 (工具, 参数) 连续 3 次 = 在打转
WRITE_TOOLS = {"write", "edit", "multiedit"}


def support_rubric() -> list[Criterion]:
    """客服/工单：与默认 rubric 完全一致，显式导出只是为了调用方不必知道内部名字。"""
    return list(DEFAULT_RUBRIC)


def _signature(call) -> str:
    return f"{call.name}:{call.args}"


def _path_of(call) -> str:
    args = call.args if isinstance(call.args, dict) else {}
    return str(args.get("file_path") or args.get("path") or "")


def _no_loop(t: Trace) -> tuple[float, str]:
    run = best = 0
    prev = None
    for call in t.tool_calls:
        sig = _signature(call)
        run = run + 1 if sig == prev else 1
        prev = sig
        best = max(best, run)
    if best >= REPEAT_LIMIT:
        return 0.0, f"连续重复同一调用 {best} 次（上限 {REPEAT_LIMIT}）"
    return 1.0, f"最长连续重复 {best} 次"


def _retry_after_error_changed(t: Trace) -> tuple[float, str]:
    hits = 0
    for prev, cur in zip(t.tool_calls, t.tool_calls[1:]):
        if prev.error and _signature(prev) == _signature(cur):
            hits += 1
    return (0.0, f"{hits} 次原封不动重试失败调用") if hits else (1.0, "报错后都改了做法")


def _read_before_write(t: Trace) -> tuple[float, str]:
    """edit 之前必须在同一轮里读过那个文件——没读过就改 = 在猜文件内容。"""
    read: set[str] = set()
    for call in t.tool_calls:
        path = _path_of(call)
        if call.name in WRITE_TOOLS and path:
            if call.name == "edit" and path not in read:
                return 0.0, f"未读取就编辑 {path}"
            read.add(path)
        elif path:
            read.add(path)
    return 1.0, "改文件前都读过"


def _turn_completed(t: Trace) -> tuple[float, str]:
    reason = t.meta.get("reason") or ("aborted" if t.meta.get("aborted") else "completed")
    return (0.0, f"回合异常结束（{reason}）") if t.meta.get("aborted") else (1.0, f"结束原因 {reason}")


def _produced_answer(t: Trace) -> tuple[float, str]:
    body = (t.output or "").strip()
    return (1.0, f"结尾答复 {len(body)} 字") if body else (0.0, "没有结尾答复")


VERIFY_TOOLS = {"read", "grep", "glob", "bash", "python", "web_fetch"}


def _verify_after_write(t: Trace) -> tuple[float, str]:
    """只写不验：一路 edit/write 到结束，却没有一次读回或跑测试。

    注意「全程只用 bash」不是缺陷——真实编码 agent 大量工作都在 shell 里。
    真正的坏味道是「改完不验证」。
    """
    writes = [c for c in t.tool_calls if c.name in WRITE_TOOLS]
    if not writes:
        return 1.0, "本轮无写操作"
    last_write = max(i for i, c in enumerate(t.tool_calls) if c.name in WRITE_TOOLS)
    after = t.tool_calls[last_write + 1:]
    # 必须看 c.ok：读一个不存在的文件（error=ENOENT）不是验证，是又犯一个错。
    # 原先只比工具名，于是「写完读了一下（但文件不存在）」也算验证通过。
    if any(c.name in VERIFY_TOOLS and c.ok for c in after):
        return 1.0, f"{len(writes)} 次写，末次写之后有成功的验证"
    attempted = any(c.name in VERIFY_TOOLS for c in after)
    if attempted:
        return 0.0, f"{len(writes)} 次写，末次写之后的验证动作全部失败"
    return 0.0, f"{len(writes)} 次写，末次写之后没有任何验证动作"


# 报错之后「如实说明失败」与「照常给结论」是两件事：
# 前者是诚实（扣分但不否决），后者是编造（一票否决）。
HONEST_FAILURE_RE = re.compile(
    r"(无法|失败|未能|不能|出错|报错|错误|失败原因|拿不到|查不到|unknown|unable|could not|"
    r"cannot|error|failed|failure|blocked|not available)", re.I)


def _error_recovered(t: Trace) -> tuple[float, str]:
    """工具报错过之后：要么真补救了，要么别宣称完成。

    这是编码 rubric 里原本完全缺失的一维——六条规则没有一条读 ToolCall.ok/error，
    于是「pytest 红了 → 结尾写全部通过」可以拿 1.0 PASS（真实 60 条轨迹判出 58 PASS）。
    """
    if not t.has_error:
        return 1.0, "无工具报错"
    last_err = max(i for i, c in enumerate(t.tool_calls) if c.error)
    recovered = any(c.ok for c in t.tool_calls[last_err + 1:])
    if recovered:
        return 1.0, "报错后有一次成功动作补回"
    if HONEST_FAILURE_RE.search(t.output or ""):
        return 0.5, "报错后未补救，但如实说明了失败"
    return 0.0, "工具报错后既未补救也未说明失败，仍照常给出结论"


def agent_rubric() -> list[Criterion]:
    # 权重合计 1.0；两个 fatal 项都是「一票否决」：回合没走完、或报错后编造结论。
    return [
        Criterion("turn_completed", 0.15, _turn_completed, fatal=True),
        Criterion("error_recovered", 0.25, _error_recovered, fatal=True),
        Criterion("no_loop", 0.15, _no_loop),
        Criterion("retry_after_error_changed", 0.15, _retry_after_error_changed),
        Criterion("read_before_write", 0.10, _read_before_write),
        Criterion("produced_answer", 0.10, _produced_answer),
        Criterion("verify_after_write", 0.10, _verify_after_write),
    ]


__all__ = ["Criterion", "agent_rubric", "support_rubric",
           "_uses_tool", "_no_tool_error", "_no_refusal",
           "_answers_expected_terms", "_within_budget"]
