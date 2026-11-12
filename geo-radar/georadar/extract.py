"""从一段模型回答里抽取：品牌提及、出现次序、情感极性、上下文。

刻意不依赖 LLM —— 抽取必须可复现、可回归。模型升级时抽取逻辑不能跟着漂。
"""
from __future__ import annotations

import re

from .models import Answer, Mention

POSITIVE = ["best", "leading", "推荐", "强大", "稳定", "优秀", "首选", "reliable", "popular", "top"]
NEGATIVE = ["worse", "limited", "expensive", "差", "不足", "昂贵", "缺点", "lack", "weak", "deprecated"]

WINDOW = 48


def _brand_regex(brand: str) -> re.Pattern:
    # 词边界匹配，允许品牌名内部有空格/连字符/点（如 "The Prompting Company"、"Filing.Lens"）
    escaped = re.escape(brand.strip())
    return re.compile(rf"(?<![\w-]){escaped}(?![\w-])", re.IGNORECASE)


def _chars_in_window(text: str, start: int, end: int) -> int:
    return max(0, end - start)


def sentiment_of(text: str) -> float:
    """词典法情感分，落在 [-1, 1]。够用，且完全可解释。"""
    low = text.lower()
    pos = sum(1 for w in POSITIVE if w in low)
    neg = sum(1 for w in NEGATIVE if w in low)
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
    hits.sort()

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
