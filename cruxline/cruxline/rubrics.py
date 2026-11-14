"""两套 rubric：一套给客服/工单类 agent（手工夹具），一套给编码 agent（真实会话轨迹）。

为什么要分开：客服场景里「工具报错」是硬否决；编码场景里报错是常态
（grep 没匹配、编译失败、测试红），真正的失败信号是「报错后原封不动重试」和
「没读过就改文件」。用同一套权重评两类任务，等于拿体温计量血压。
"""

from __future__ import annotations

import json
import re
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
from .trace import Trace

REPEAT_LIMIT = 3          # 同一 (工具, 参数) 连续 3 次 = 在打转
WRITE_TOOLS = {"write", "edit", "multiedit"}

# 真实编码轨迹里改名/改文件大多走 bash：sed -i、tee -a、>> 追加。
# 只认 write/edit/multiedit，「没读过就改」对这类原地修改完全不触发。
#
# 口径限定在「原地修改代码文件」：
#   · `cat > f <<EOF` 从轨迹里无法区分新建与覆盖，新建本来不需要先读 —— 不判（假阳守卫见测试）；
#   · 往 .md/.log 追加是生成产物，不判。
# sed -i 的语法是 `sed -i SCRIPT FILE`，脚本在中间，所以单独按「行尾最后一个 token」取目标。
_INPLACE_RE = re.compile(
    r"(?:tee\s+-a\s+|(?<![0-9&])>>\s*)['\"]?(?P<path>[^\s;|&<>'\"]+)['\"]?"
)
_SED_INPLACE_RE = re.compile(r"\bsed\s+-i")
_CODE_SUFFIX = {
    ".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".java", ".rb", ".php", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}
_NOISE_TARGETS = re.compile(r"^/dev/(?:null|stdout|stderr|tty|fd/.*)$")


def _bash_inplace_paths(call) -> list[str]:
    """从 bash 命令里认出被「原地修改」的代码文件。

    只认 sed -i / tee -a / >> 三种，且目标后缀必须是代码或配置。
    局限写明白：heredoc 覆盖既有文件判不了（与新建同形），宁可漏判。
    """
    if call.name != "bash":
        return []
    args = call.args if isinstance(call.args, dict) else {}
    cmd = str(args.get("command") or "")
    out: list[str] = []

    def _keep(raw: str) -> None:
        path = raw.strip("'\"")
        if not path or _NOISE_TARGETS.match(path):
            return
        if "/" not in path and "." not in path:
            return
        if "." not in path:                          # 无后缀，不像文件
            return
        if "." + path.rsplit(".", 1)[-1] not in _CODE_SUFFIX:
            return
        if path not in out:
            out.append(path)

    for line in cmd.splitlines():
        if _SED_INPLACE_RE.search(line):
            toks = line.split()
            if toks:
                _keep(toks[-1])
        for m in _INPLACE_RE.finditer(line):
            _keep(m.group("path"))
    return out


def support_rubric() -> list[Criterion]:
    """客服/工单：与默认 rubric 完全一致，显式导出只是为了调用方不必知道内部名字。"""
    return list(DEFAULT_RUBRIC)


def _signature(call) -> str:
    """签名的用途是「判两次调用是不是同一件没进展的事」。

    dict 的 repr 依插入顺序，同一个 read(file_path=x, offset=1, limit=20)
    换一种键序就成了另一个签名 —— 键序对调 6 次读同一文件，no_loop 记「最长重复 1 次」。
    所以先规范化：键排序、非 JSON 类型退化为 str。
    """
    args = call.args if isinstance(call.args, dict) else {}
    try:
        canon = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canon = repr(sorted(args.items(), key=lambda kv: str(kv[0])))
    return f"{call.name}:{canon}"


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
        # bash 写盘先展开成「写了哪些文件」，再走同一套判定
        bash_writes = _bash_inplace_paths(call)
        if call.name in WRITE_TOOLS and path:
            if call.name in ("edit", "write") and path not in read and call.name == "edit":
                return 0.0, f"未读取就编辑 {path}"
            read.add(path)
        elif bash_writes:
            for w in bash_writes:
                if w not in read:
                    return 0.0, f"未读取就原地修改 {w}（bash）"
                read.add(w)
        elif path:
            read.add(path)
    return 1.0, "改文件前都读过"


def _turn_completed(t: Trace) -> tuple[float, str]:
    """回合是否正常走完。

    判据是「结束原因」，不是某个导出器才会写的布尔字段：只认 `aborted` 时，
    一条 `reason=error` 却没有 `aborted` 的轨迹会拿满 0.15 分、还打印
    「结束原因 error」—— 读日志的人以为它被抓了，实际一分没扣。
    `interrupted` 是用户/压缩打断，不是 agent 的错，仍给满分。
    """
    reason = t.meta.get("reason") or ("aborted" if t.meta.get("aborted") else "completed")
    if t.meta.get("aborted") or reason == "error":
        return 0.0, f"回合异常结束（{reason}）"
    return 1.0, f"结束原因 {reason}"


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
