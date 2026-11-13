"""把 dsh 会话日志导成 cruxline 能评分的轨迹。

真实 agent 轨迹里没有"标准答案"，所以导出的是过程：每轮的用户输入、工具调用序列、
每次调用的结果与报错、以及最后的答复。评分器只看过程，不看答案对错。

    python scripts/export_dsh_traces.py --sessions ~/.dsh/sessions --limit 40 --min-steps 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def decompress(path: Path) -> str:
    return subprocess.run(["zstd", "-dc", str(path)], capture_output=True,
                          check=True).stdout.decode("utf-8", "replace")


def text_of(message: dict) -> str:
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(parts).strip()


import re

# 真实 2326 次调用里 83 次含 Traceback、其中 46 次原实现记 error 为空；
# 5 次 "command not found" 全部为空 —— 依赖 error 的致命否决在真实链路大半不触发。
# 判据按「工具自己承认失败」而不是两种字面写法：
_ERROR_PATTERNS = [
    re.compile(r"^\s*Traceback \(most recent call last\)", re.M),
    re.compile(r"\bcommand not found\b|^\s*[\w.+-]+: not found\b", re.M),
    re.compile(r"\bNo such file or directory\b"),
    re.compile(r"\bPermission denied\b"),
    re.compile(r"\bnpm ERR!"),
    re.compile(r"^\s*(?:Error|ERROR|error):\s*(?!0\b)\S", re.M),
    re.compile(r"\b(?:FAILED|FAILURES)\b"),
    re.compile(r"\bsegmentation fault\b", re.I),
]

_EXIT_CODE_RE = re.compile(r"exit code:\s*(-?\d+)")
# 计数式表述（"error: 0 warnings"、"0 errors"）不是失败，匹配到了也不算
_ZERO_COUNT_RE = re.compile(r"\b0\s+(?:errors?|failures?|warnings?)\b", re.I)


def classify_error(body: str) -> str:
    """返回错误摘要；没有错误返回空串。

    判据顺序：先看退出码（最硬的信号），再看已知失败字样。
    "exit code: 0" 明确成功，不做后续字样匹配（测试输出里常带 error 字样）。
    """
    if not body:
        return ""
    m = _EXIT_CODE_RE.search(body)
    if m:
        code = int(m.group(1))
        if code != 0:
            return body.splitlines()[0][:200]
        # 退出码 0 → 命令成功，后面的字样是内容不是状态
        return ""
    if _ZERO_COUNT_RE.search(body) and not any(
            pat.search(_ZERO_COUNT_RE.sub("", body)) for pat in _ERROR_PATTERNS):
        return ""
    for pat in _ERROR_PATTERNS:
        if pat.search(body):
            for line in body.splitlines():
                if line.strip():
                    return line.strip()[:200]
    return ""


def export_session(path: Path, min_steps: int, limit: int) -> list[dict]:
    try:
        raw = decompress(path)
    except subprocess.CalledProcessError:
        return []
    turns: dict[int, dict] = {}
    user_text: dict[int, str] = {}
    results: dict[str, dict] = {}
    order: list[dict] = []

    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        t, data = e.get("type"), e.get("data") or {}
        if t == "user/message" and (data.get("source") or {}).get("kind") == "user":
            turn = max(turns) if turns else 0
            user_text[turn] = text_of(data)
        elif t == "turn/start":
            turn = data.get("turn")
            turns[turn] = {"turn": turn, "calls": [], "output": "", "aborted": False,
                           "reason": "no-end", "started": e.get("time")}
            order.append(turns[turn])
        elif t == "tool/call":
            turn = data.get("turn")
            call = {"name": data.get("name"),
                    "args": _parse_args(data.get("arguments")),
                    "result": "", "error": ""}
            calls = turns.setdefault(turn, {"turn": turn, "calls": [], "output": "",
                                            "aborted": False, "reason": "no-end"})
            calls["calls"].append(call)
            results[data.get("callId")] = call
        elif t == "tool/result":
            msg = data.get("message") or {}
            call = results.get(msg.get("toolCallId"))
            if call is None:
                continue
            body = text_of(msg)
            call["result"] = body[:2000]
            call["error"] = classify_error(body)
        elif t == "assistant/message":
            turn = data.get("turn")
            body = text_of(data.get("message") or {})
            if body and turn in turns:
                turns[turn]["output"] = body
        elif t == "turn/end":
            turn = data.get("turn")
            if turn in turns:
                reason = (data.get("reason") or {}).get("kind") or "unknown"
                turns[turn]["reason"] = reason
                # 只有「异常结束」才算失败；用户主动打断或上下文压缩打断不是 agent 的错
                turns[turn]["aborted"] = reason not in ("completed", "interrupted")
                turns[turn]["ended"] = e.get("time")

    out = []
    for turn in order:
        if len(turn["calls"]) < min_steps:
            continue
        if len(out) >= limit:
            break
        out.append({
            "case_id": f"{path.parent.name[:17]}#t{turn['turn']}",
            "input": user_text.get(turn["turn"], ""),
            "output": turn["output"],
            "tool_calls": turn["calls"],
            "meta": {"session": path.parent.name, "turn": turn["turn"],
                     "steps": len(turn["calls"]), "aborted": turn["aborted"],
                     "reason": turn.get("reason"),
                     "started": turn.get("started"), "ended": turn.get("ended")},
        })
    return out


def _parse_args(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": str(raw)[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=str(Path.home() / ".dsh/sessions"))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--min-steps", type=int, default=3)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data/traces.jsonl"))
    a = ap.parse_args()

    root = Path(a.sessions).expanduser()
    files = sorted(root.rglob("session.v4.jsonl.zstd"), key=lambda p: p.stat().st_size,
                   reverse=True)
    traces: list[dict] = []
    for f in files:
        traces.extend(export_session(f, a.min_steps, a.limit - len(traces)))
        if len(traces) >= a.limit:
            break
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in traces) + "\n")
    print(f"导出 {len(traces)} 条轨迹 → {out}")
    if traces:
        steps = sorted(t["meta"]["steps"] for t in traces)
        reasons = {}
        for t in traces:
            reasons[t["meta"]["reason"]] = reasons.get(t["meta"]["reason"], 0) + 1
        print(f"步数中位数 {steps[len(steps)//2]}，最多 {steps[-1]}，"
              f"结束原因 {reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
