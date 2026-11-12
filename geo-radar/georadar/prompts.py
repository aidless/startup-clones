"""提示词集生成：GEO 的核心资产是「买家会怎么问 AI」，而不是品牌自己怎么自我介绍。

原则：提示词里绝不出现目标品牌名 —— 出现即污染，模型会顺着你给的词回答。
"""
from __future__ import annotations

import hashlib

from .models import Prompt

TEMPLATES = [
    ("discovery", "best {category} in 2026"),
    ("discovery", "top {category} tools for {audience}"),
    ("discovery", "{category} 推荐"),
    ("discovery", "{category} 哪个好"),
    ("comparison", "{category} alternatives"),
    ("comparison", "compare {category} options"),
    ("comparison", "{category} vs traditional approach"),
    ("evaluation", "how to choose a {category}"),
    ("evaluation", "what should I look for in a {category}"),
    ("problem", "how do I solve {problem}"),
]

AUDIENCES = ["startups", "enterprises", "developers", "agencies", "smb"]

DEFAULT_PROBLEMS = [
    "software outages",
    "audit preparation",
    "brand visibility in AI search",
]


def _pid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def generate(
    category: str,
    audiences: list[str] | None = None,
    problems: list[str] | None = None,
    limit: int | None = None,
) -> list[Prompt]:
    """按模板 × 受众（× 问题）展开成提示词集，去重后返回。"""
    audiences = audiences or AUDIENCES[:3]
    problems = problems if problems is not None else DEFAULT_PROBLEMS
    out: list[Prompt] = []
    seen: set[str] = set()

    for intent, tpl in TEMPLATES:
        if "{audience}" in tpl:
            variants = [tpl.format(category=category, audience=a) for a in audiences]
        elif "{problem}" in tpl:
            variants = [tpl.format(problem=p) for p in problems]
        else:
            variants = [tpl.format(category=category)]
        for text in variants:
            text = " ".join(text.split())
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            out.append(Prompt(id=_pid(intent, text), text=text, intent=intent))

    # 先截断再排序：limit 应该保留模板宽度（覆盖不同意图），而不是被字母序砍成单一意图
    if limit:
        out = out[:limit]
    out.sort(key=lambda p: (p.intent, p.text))
    return out
