"""版本回归：新版 agent 是「真变好」还是「把别的用例弄坏了」。

只看总通过率是投研级别的错误 —— 60% → 62% 可能是修好 5 个、弄坏 3 个，
而弄坏的 3 个往往正是大客户在用的场景。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RegressReport:
    before_rate: float
    after_rate: float
    regressions: list[str] = field(default_factory=list)   # pass → fail
    fixes: list[str] = field(default_factory=list)         # fail → pass
    still_failing: list[str] = field(default_factory=list)
    still_passing: int = 0
    dropped: list[str] = field(default_factory=list)       # 基线里有、这次没跑

    @property
    def delta(self) -> float:
        return round(self.after_rate - self.before_rate, 4)

    @property
    def verdict(self) -> str:
        if self.dropped:
            return "block"        # 用例被删掉不是改善，是掩盖
        if self.regressions and self.delta <= 0:
            return "block"        # 净收益 ≤ 0 且有回归 → 直接拦
        if self.regressions:
            return "review"       # 有涨但弄坏了东西 → 人来决定
        if self.delta > 0:
            return "ship"
        return "neutral"

    def to_markdown(self) -> str:
        lines = [
            f"通过率 {self.before_rate:.1%} → {self.after_rate:.1%}（{self.delta:+.1%}）",
            f"结论：**{self.verdict}** · 回归 {len(self.regressions)} · 修复 {len(self.fixes)}",
        ]
        if self.dropped:
            lines.append(f"未执行用例（{len(self.dropped)}）：" + ", ".join(self.dropped)
                         + " —— 用例集不一致，通过率不可比")
        if self.regressions:
            lines.append("回归用例：" + ", ".join(self.regressions))
        if self.fixes:
            lines.append("修复用例：" + ", ".join(self.fixes))
        return "\n".join(lines)


def diff(baseline: dict[str, bool], current: dict[str, bool]) -> RegressReport:
    ids = sorted(set(baseline) & set(current))
    if not ids:
        raise ValueError("两次运行没有交集，无法比较")
    # 基线里有、这次没跑的用例：直接把失败用例删掉就能把通过率刷到 100%，
    # 这不是改善而是掩盖（审查复现：3 条全 FAIL → 留 1 条 PASS → 0.0% 变 100% 判 ship）。
    dropped = sorted(set(baseline) - set(current))
    regressions = [i for i in ids if baseline[i] and not current[i]]
    fixes = [i for i in ids if not baseline[i] and current[i]]
    return RegressReport(
        before_rate=round(sum(baseline[i] for i in ids) / len(ids), 4),
        after_rate=round(sum(current[i] for i in ids) / len(ids), 4),
        regressions=regressions,
        fixes=fixes,
        still_failing=[i for i in ids if not baseline[i] and not current[i]],
        still_passing=sum(1 for i in ids if baseline[i] and current[i]),
        dropped=dropped,
    )
