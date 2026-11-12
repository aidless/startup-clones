"""可见性指标：份额、覆盖率、平均位次、引用源分布。

所有指标必须能用一个定义写清楚，且分母写死 —— GEO 报表最常见的问题是
分母来回换，导致看着涨了其实是样本变了。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import Answer, Mention


@dataclass
class BrandStats:
    brand: str
    mentions: int = 0
    prompts_seen: int = 0          # 提到过该品牌的提示词条数（按 prompt 去重）
    positions: list[int] | None = None
    sentiment: float = 0.0

    def __post_init__(self) -> None:
        if self.positions is None:
            self.positions = []

    @property
    def share_of_voice(self) -> float:
        total = getattr(self, "_total_mentions", 0)
        return round(self.mentions / total, 4) if total else 0.0

    @property
    def avg_position(self) -> float:
        return round(sum(self.positions) / len(self.positions), 2) if self.positions else 0.0


def brand_stats(mentions: list[Mention], prompts_total: int) -> dict[str, BrandStats]:
    stats: dict[str, BrandStats] = {}
    total = len(mentions)
    per_prompt: dict[str, set[str]] = defaultdict(set)

    for m in mentions:
        s = stats.setdefault(m.brand, BrandStats(brand=m.brand))
        s.mentions += 1
        s.positions.append(m.position)
        s._sent_sum = getattr(s, "_sent_sum", 0.0) + m.sentiment
        per_prompt[m.brand].add(m.prompt_id)

    for brand, s in stats.items():
        s._total_mentions = total
        s.prompts_seen = len(per_prompt[brand])
        s._prompts_total = prompts_total
        s.sentiment = round(getattr(s, "_sent_sum", 0.0) / s.mentions, 3) if s.mentions else 0.0

    return stats


def visibility_rate(stats: dict[str, BrandStats], brand: str, prompts_total: int) -> float:
    s = stats.get(brand)
    if not s or prompts_total == 0:
        return 0.0
    return round(s.prompts_seen / prompts_total, 4)


def citation_domains(answers: list[Answer]) -> Counter:
    c: Counter = Counter()
    for a in answers:
        for cit in a.citations:
            c[cit.domain] += 1
    return c


def citation_share(counter: Counter) -> dict[str, float]:
    total = sum(counter.values())
    if not total:
        return {}
    return {d: round(n / total, 4) for d, n in counter.most_common()}


def rank_distribution(mentions: list[Mention], brand: str) -> dict[int, int]:
    d: Counter = Counter(m.position for m in mentions if m.brand == brand)
    return dict(sorted(d.items()))


def gap_report(stats: dict[str, BrandStats], ours: str, competitors: list[str]) -> dict:
    """我们 vs 竞品的差距。没有竞品数据时返回空差。"""
    our = stats.get(ours)
    if not our:
        return {"ours": ours, "gap_sov": None, "gap_visibility": None, "leader": competitors[0] if competitors else None}
    best = max(((c, stats.get(c)) for c in competitors), key=lambda kv: kv[1].mentions if kv[1] else 0, default=(None, None))
    if not best[1]:
        return {"ours": ours, "gap_sov": None, "gap_visibility": None, "leader": None}
    return {
        "ours": ours,
        "leader": best[0],
        "gap_sov": round(best[1].share_of_voice - our.share_of_voice, 4),
        "gap_visibility": round(best[1].prompts_seen - our.prompts_seen),
        "gap_position": round(best[1].avg_position - our.avg_position, 2),
    }
