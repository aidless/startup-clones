"""从一段模型回答里抽取：品牌提及、出现次序、情感极性、上下文。

刻意不依赖 LLM —— 抽取必须可复现、可回归。模型升级时抽取逻辑不能跟着漂。
"""
from __future__ import annotations

import re

from .models import Answer, Mention

POSITIVE = ["best", "leading", "推荐", "强大", "稳定", "优秀", "首选", "reliable", "popular", "top"]
NEGATIVE = ["worse", "limited", "expensive", "差", "不足", "昂贵", "缺点", "lack", "weak", "deprecated"]

# 英文情感词必须按词匹配：`"top" in "desktop"` 会把 "A desktop app" 判成褒义（实测复现）。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RES: dict[str, re.Pattern] = {}


def _word_pattern(word: str) -> re.Pattern:
    """英文词用词边界，中文词仍用子串（中文不分词，子串就是正确语义）。"""
    if word not in _WORD_RES:
        if _CJK_RE.search(word):
            _WORD_RES[word] = re.compile(re.escape(word))
        else:
            _WORD_RES[word] = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    return _WORD_RES[word]

WINDOW = 48


def _brand_regex(brand: str) -> re.Pattern:
    # 词边界匹配，允许品牌名内部有空格/连字符/点（如 "The Prompting Company"、"Filing.Lens"）
    escaped = re.escape(brand.strip())
    # 不能用 \w 做边界：Python 的 \w 含汉字，中文里品牌名紧贴汉字（「推荐Acme这个工具」）
    # 时左边界不成立，全部漏检 —— 而提示词模板一半是中文，等于一半样本品牌识别失效。
    # 这里只把「拉丁字母/数字/下划线/连字符」当作「词内」，汉字与标点都算边界。
    return re.compile(rf"(?<![A-Za-z0-9_-]){escaped}(?![A-Za-z0-9_-])", re.IGNORECASE)


def _chars_in_window(text: str, start: int, end: int) -> int:
    return max(0, end - start)


def sentiment_of(text: str) -> float:
    """词典法情感分，落在 [-1, 1]。够用，且完全可解释。"""
    pos = sum(1 for w in POSITIVE if _word_pattern(w).search(text))
    neg = sum(1 for w in NEGATIVE if _word_pattern(w).search(text))
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 3)


def find_mentions(answer: Answer, brands: list[str]) -> list[Mention]:
    """返回按出现位置排序的提及列表；position 从 1 开始。"""
    hits: list[tuple[int, str]] = []
    for brand in brands:
        m = _brand_regex(brand).search(answer.text)
        if m:
            hits.append((m.start(), brand))
    # 互为前缀的品牌（Bill 与 Bill.com）会在同一处各命中一次，占掉两个位次，
    # 把「第二个品牌」的位置虚推一位 —— 位次是报表的核心指标，不能这么飘。
    # 规则：同一处只留最长的那个；跨处重叠（一个 span 被另一个完全包住）也只留长的。
    spans: list[tuple[int, int, str]] = []
    for offset, brand in hits:
        spans.append((offset, offset + len(brand), brand))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept: list[tuple[int, int, str]] = []
    for start, end, brand in spans:
        if any(start >= ks and end <= ke for ks, ke, _ in kept):
            continue
        kept = [k for k in kept if not (k[0] >= start and k[1] <= end)]
        kept.append((start, end, brand))
    hits = sorted((start, brand) for start, _end, brand in kept)

    out: list[Mention] = []
    for rank, (offset, brand) in enumerate(hits, start=1):
        lo = max(0, offset - WINDOW * 2)
        hi = min(len(answer.text), offset + len(brand) + WINDOW)
        ctx = answer.text[lo:hi].replace("\n", " ").strip()
        out.append(
            Mention(
                prompt_id=answer.prompt_id,
                brand=brand,
                position=rank,
                char_offset=offset,
                sentiment=sentiment_of(ctx),
                context=ctx,
            )
        )
    return out


def mentioned(answer: Answer, brand: str) -> bool:
    return bool(_brand_regex(brand).search(answer.text))
