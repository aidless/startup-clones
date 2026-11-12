"""记忆与上下文预算。

常驻 agent 的上下文不是「越长越好」：一个接了三年的收件箱会把上下文撑爆，
所以必须显式做三件事 —— 事实抽取（可检索）、滚动摘要（保时间线）、预算截断（保可用）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .channels import Inbound


def est_tokens(text: str) -> int:
    """粗估 token：中文约 1 token/字，英文约 1 token/4 字符。取折中 1/3 并保底 1。"""
    return max(1, len(text) // 3)


@dataclass
class Fact:
    key: str
    value: str
    source: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class Memory:
    def __init__(self, persona: str = "", max_facts: int = 200, budget_tokens: int = 600):
        self.persona = persona
        self.max_facts = max_facts
        self.budget = budget_tokens
        self.facts: dict[str, Fact] = {}
        self.transcript: list[Inbound] = []
        self.summaries: list[str] = []

    # ---- 写入 ----
    def remember(self, key: str, value: str, source: str = "") -> Fact:
        f = Fact(key=key, value=value, source=source)
        self.facts[key] = f
        if len(self.facts) > self.max_facts:
            oldest = min(self.facts.values(), key=lambda x: x.ts)
            self.facts.pop(oldest.key, None)
        return f

    def observe(self, inbound: Inbound) -> None:
        self.transcript.append(inbound)

    def summarize(self, text: str) -> None:
        self.summaries.append(text)

    # ---- 读取 ----
    def recall(self, query: str, k: int = 5) -> list[Fact]:
        q = {w for w in query.lower().split() if w}
        if not q:
            return list(self.facts.values())[-k:]
        scored = []
        for f in self.facts.values():
            hay = f"{f.key} {f.value}".lower()
            score = sum(1 for w in q if w in hay)
            if score:
                scored.append((score, f.ts, f))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [f for _, _, f in scored[:k]]

    def context(self, query: str = "", budget_tokens: int | None = None) -> str:
        """按预算拼上下文：人设 → 相关事实 → 滚动摘要 → 最近对话（超预算先砍对话）。"""
        budget = budget_tokens or self.budget
        parts: list[str] = []
        used = 0

        def add(block: str) -> bool:
            nonlocal used
            cost = est_tokens(block)
            if used + cost > budget:
                return False
            parts.append(block)
            used += cost
            return True

        if self.persona:
            add(f"[人设] {self.persona}")
        facts = self.recall(query)
        if facts:
            body = "\n".join(f"- {f.key}: {f.value}" for f in facts)
            add(f"[已知事实]\n{body}")
        if self.summaries:
            add("[历史摘要]\n" + "\n".join(self.summaries[-3:]))

        # 对话从最新往前加，加不下就停
        convo: list[str] = []
        for m in reversed(self.transcript[-20:]):
            line = f"{m.sender}: {m.text}"
            if not add(f"[对话] {line}"):
                break
            convo.append(line)
        return "\n".join(parts)
