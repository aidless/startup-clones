"""轨迹模型：一次 agent 运行 = 输入 + 工具调用序列 + 输出 + 元数据。

评测的对象是轨迹，不是最终一句话。工具调用里藏着 90% 的失败模式
（选错工具、死循环、把错误结果当成功继续）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    result: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Trace:
    case_id: str
    input: str
    output: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # expected_terms / max_steps / tags —— 由人造 fixtures 或线上回放提供
    meta: dict = field(default_factory=dict)

    @property
    def steps(self) -> int:
        return len(self.tool_calls)

    @property
    def has_error(self) -> bool:
        return any(not t.ok for t in self.tool_calls)

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        meta = dict(d.get("meta") or {})
        # 结束原因与「是否被打断」是同一件事的两种写法，不同导出器只给一个。
        # 在这里补齐，避免下游各读一半（`turn_completed` 曾只认 aborted，
        # 于是 `reason=error` 的轨迹拿满分）。
        if meta.get("reason") == "error":
            meta["aborted"] = True
        elif meta.get("aborted") and not meta.get("reason"):
            meta["reason"] = "aborted"
        else:
            meta.setdefault("aborted", False)
            meta.setdefault("reason", "completed")
        return cls(
            case_id=str(d.get("case_id") or d.get("id")),
            input=d.get("input", ""),
            output=d.get("output", d.get("answer", "")),
            tool_calls=[ToolCall(**t) if isinstance(t, dict) else t for t in d.get("tool_calls", [])],
            meta=meta,
        )


def load_traces(items: list[dict]) -> list[Trace]:
    return [Trace.from_dict(x) for x in items]
