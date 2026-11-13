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


CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 概念覆盖率里「不能单独作证」的词。
# `full-time` 会被分词器切成 full / time，于是任何含 "time"（"from time to time"）
# 的段落都算讲到了员工——实测 419 个 chunk 里 39 个拿满覆盖，Item 1¶35 通篇没有员工词。
# `equivalent` 同病："cash equivalents" 到处都有。（这些词按 idf 也拦不住：
# 在 Apple 的 10-K 里 time 的 idf 是 2.8，比 employees 的 3.2 只低一点。）
_AMBIGUOUS_GROUP_TOKENS = frozenset({
    "full", "time", "part", "equivalent", "number", "total", "based",
    "person", "people", "team", "member", "members", "staff", "year", "years",
})


def _concept_terms(term: str) -> list[str]:
    """一个概念词条里可以作为证据的 token。全是歧义词就返回空 —— 该词条作废。"""
    return [t for t in tokenize(term) if len(t) >= 2 and t not in _AMBIGUOUS_GROUP_TOKENS]


def coverage(query: str, hit: Hit, idf=None, groups: list[list[str]] | None = None) -> float:
    """查询词被命中的比例 —— 用来判「答非所问」。

    分母只算「可能被命中」的词：中文单字在英文语料里按构造就不可能命中，
    把它们算进分母会让中文提问永远判成证据不足（真实 10-K 上实测：上限 ~20%）。
    拉丁词一个都没有时才退回全部词（纯中文且没走词表扩写的场景）。
    """
    appear_all = set(hit.matched) | set(tokenize(hit.chunk.text))
    if groups:
        # 概念级覆盖：一个概念算命中，只要那组英文词里**有一个**出现在段落中。
        # 早先要求"过半"——实测把 9/20 家公司的"员工数"提问判成证据不足：
        # 员工那组有五个词，正文里通常只写 employees 一个。
        covered = total = 0
        for g in groups:
            # 词表里的词可能带连字符（full-time），而分词器按 [a-z0-9]+ 切，
            # 不先拆开就永远匹配不上，整个概念被判 0。
            terms = [tok for term in g for tok in _concept_terms(term)]
            if not terms:
                continue
            total += 1
            if any(t in appear_all for t in terms):
                covered += 1
        if total:
            return covered / total

    q = set(tokenize(query))
    if not q:
        return 0.0
    latin = {t for t in q if not CJK_RE.search(t) and len(t) >= 2}
    denom = latin or q
    appear = set(hit.matched) | set(tokenize(hit.chunk.text))
    if idf is None:
        return len(denom & appear) / len(denom)
    # IDF 加权：在 Apple 的 10-K 里 "apple" 遍地都是，靠它命中不能算「答上了」；
    # "headcount"这类词才带信息量。不加权时 CEO 生日会被 Apple Arcade 那段骗过去。
    w_all = sum(max(idf(t), 0.01) for t in denom)
    w_hit = sum(max(idf(t), 0.01) for t in denom & appear)
    return w_hit / w_all if w_all else 0.0
