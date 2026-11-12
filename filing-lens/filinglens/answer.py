"""答案合成：先查结构化事实，再回落到原文摘录；任何答案都必须带引用，否则拒答。

这是本项目的核心契约：
- 没有引用 = 没有答案（返回 status=insufficient_evidence，而不是编一段话）。
- 数字类问题只走 XBRL，不走文本 —— 文本里的数字是别人抄错的来源。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import facts as F
from .edgar import Chunk
from .index import BM25Index, coverage, tokenize

MIN_COVERAGE = 0.34
# 拒答话术必须统一：客户看到两种不同的"答不了"会以为是 bug
REFUSAL = "文件里没有足够证据回答这个问题（证据不足，不作答）。"

# 数字通道的门槛：只要问题里随便出现 "revenue" 就走 XBRL 会抢答
# （"top customers concentration revenue" 被答成营收同比，明显答非所问）。
NUMERIC_CUES = ("how much", "what was", "what were", "同比增长", "同比", "多少", "金额", "revenue in")
QUALITATIVE_CUES = ("risk", "why", "how do", "how does", "explain", "strategy", "customer", "what are", "为什么")


def is_numeric_question(q: str) -> bool:
    low = q.lower()
    if any(c in low for c in QUALITATIVE_CUES):
        return False
    if len(tokenize(q)) <= 4:
        return True
    return any(c in low for c in NUMERIC_CUES)


@dataclass
class Citation:
    ref: str
    quote: str
    kind: str = "text"  # text | xbrl


@dataclass
class Response:
    kind: str                 # metric | excerpt | insufficient_evidence
    status: str               # ok | no_data | insufficient_evidence
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0

    def render(self) -> str:
        head = f"[{self.status}] {self.text}"
        if not self.citations:
            return head
        lines = [head, "", "出处："]
        for i, c in enumerate(self.citations, 1):
            lines.append(f"  [{i}] ({c.kind}) {c.ref}")
            lines.append(f"      > {c.quote[:220]}")
        return "\n".join(lines)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


class Answerer:
    def __init__(self, chunks: list[Chunk], facts_conn: sqlite3.Connection | None = None):
        self.index = BM25Index().add(chunks)
        self.facts = facts_conn

    # ---- 数字通道 ----
    def _metric_answer(self, question: str) -> Response | None:
        if not self.facts:
            return None
        if not is_numeric_question(question):
            return None
        hit = F.resolve_metric(question)
        if not hit:
            return None
        metric = hit[1]
        series = F.annual_series(self.facts, metric)
        if not series:
            return Response(kind="metric", status="no_data",
                            text=f"文件里没有 {metric} 的年度数据（XBRL 未披露）。")
        last = series[-1]
        changes = F.yoy(series)
        seg = "、".join(f"FY{fy} {c:+.1%}" for fy, c in changes) or "无同比（仅一年）"
        text = (f"{metric}：FY{last.fy} 为 {F.fmt_money(last.val, last.unit)}；"
                f"同比变化 {seg}。")
        cites = [
            Citation(ref=f"XBRL:{f.tag}@FY{f.fy}", quote=f"{f.tag} = {f.val:,.0f} {f.unit}", kind="xbrl")
            for f in series[-3:]
        ]
        return Response(kind="metric", status="ok", text=text, citations=cites,
                        confidence=1.0 if len(series) >= 2 else 0.7)

    # ---- 文本通道 ----
    def _excerpt_answer(self, question: str, k: int = 5) -> Response:
        hits = self.index.search(question, k=k)
        if not hits:
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL, citations=[])
        best = hits[0]
        cov = coverage(question, best)
        if cov < MIN_COVERAGE:
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL + f"（最相关段落只覆盖 {cov:.0%} 的查询词）",
                            citations=[])

        q = set(tokenize(question))
        scored = []
        for i, sent in enumerate(_sentences(best.chunk.text)):
            overlap = len(q & set(tokenize(sent)))
            if overlap:
                scored.append((overlap, i, sent))
        scored.sort(key=lambda x: (-x[0], x[1]))
        keep = sorted(scored[:2], key=lambda x: x[1])
        quote = " ".join(s[2] for s in keep) or best.chunk.text[:400]

        return Response(
            kind="excerpt", status="ok", text=quote,
            citations=[Citation(ref=best.chunk.ref, quote=quote, kind="text")],
            confidence=round(cov, 3),
        )

    def ask(self, question: str) -> Response:
        metric = self._metric_answer(question)
        if metric and metric.status == "ok":
            return metric
        text = self._excerpt_answer(question)
        return text if text.status == "ok" else (metric or text)
