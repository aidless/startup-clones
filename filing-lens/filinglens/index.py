"""检索：BM25（纯 Python，无外部依赖），支持按 Item 过滤。

为什么不用向量库做第一层：
- 财报问答的查询词高度专有（"contract liabilities"、"Item 1A"），词法匹配比稠密向量更准；
- 可复现、可回归、无需 embedding 成本；
- 需要语义召回时再叠一层向量，但词法层必须留在前面当锚。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .edgar import Chunk

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")

STOP = set("""a an the of to in for on and or is are was were be been with as at by from that this
it its we our us they their than then which who whom whose not no do does did have has had will
would could should may might can""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP]


@dataclass
class Hit:
    chunk: Chunk
    score: float
    matched: list[str]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        self.doc_tokens: list[Counter] = []
        self.doc_len: list[int] = []
        self.df: Counter = Counter()
        self.avg_len: float = 0.0

    def add(self, chunks: list[Chunk]) -> "BM25Index":
        for c in chunks:
            toks = tokenize(c.text)
            self.chunks.append(c)
            self.doc_tokens.append(Counter(toks))
            self.doc_len.append(len(toks))
            for t in set(toks):
                self.df[t] += 1
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        return self

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self.df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5, items: list[str] | None = None) -> list[Hit]:
        q = tokenize(query)
        if not q or not self.chunks:
            return []
        scores: list[float] = []
        for i, tf in enumerate(self.doc_tokens):
            if items and self.chunks[i].item not in items:
                scores.append(0.0)
                continue
            s = 0.0
            dl = self.doc_len[i] or 1
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                s += self._idf(term) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
                )
            scores.append(s)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        out = []
        for i in order:
            if scores[i] <= 0:
                continue
            matched = [t for t in q if self.doc_tokens[i].get(t)]
            out.append(Hit(chunk=self.chunks[i], score=round(scores[i], 4), matched=matched))
        return out


def coverage(query: str, hit: Hit) -> float:
    """查询词被命中的比例 —— 用来判「答非所问」。"""
    q = set(tokenize(query))
    if not q:
        return 0.0
    return len(q & set(hit.matched + tokenize(hit.chunk.text))) / len(q)
