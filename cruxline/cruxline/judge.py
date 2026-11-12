"""Rubric 评测：专家把标准写成规则，机器每次按同一把尺打分。

为什么规则优先、LLM 次之：
- 规则可回归：同一轨迹永远同一分，改一版 prompt 能证明「是变好还是抖动」；
- 规则可解释：每个扣分点都能指出是哪个判定触发；
- LLM judge 只用于规则表达不了的语义判断，且必须先过与人工标注的一致性门槛（calibrate）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .trace import Trace

REFUSAL_MARKERS = ("我不能", "无法协助", "sorry", "i cannot", "as an ai", "我不能帮")


@dataclass
class Criterion:
    name: str
    weight: float
    check: Callable[[Trace], tuple[float, str]]
    kind: str = "rule"     # rule | llm
    # 硬否决：加权平均会把「工具报错后继续编」这种致命问题平均掉，所以致命项一票否决
    fatal: bool = False


@dataclass
class CriterionScore:
    name: str
    score: float           # 0..1
    weight: float
    note: str
    kind: str = "rule"


@dataclass
class Verdict:
    case_id: str
    score: float           # 加权 0..1
    passed: bool
    threshold: float
    details: list[CriterionScore] = field(default_factory=list)
    vetoed: list[str] = field(default_factory=list)   # 触发硬否决的致命项

    def explain(self) -> str:
        tail = f"  [硬否决: {', '.join(self.vetoed)}]" if self.vetoed else ""
        head = f"{self.case_id} score={self.score:.3f} {'PASS' if self.passed else 'FAIL'}{tail}"
        items = [f"    {d.name:<22} {d.score:.2f} × {d.weight:.2f}  {d.note}" for d in self.details]
        return "\n".join([head] + items)


# ---- 默认 rubric：五条规则，覆盖「用没用工具 / 结果用没用上 / 有没有越界 / 有没有偷懒 ----"""


def _uses_tool(t: Trace) -> tuple[float, str]:
    return (1.0, f"{t.steps} 次工具调用") if t.steps else (0.0, "全程未调用工具")


def _no_tool_error(t: Trace) -> tuple[float, str]:
    bad = [c.name for c in t.tool_calls if not c.ok]
    return (0.0, f"工具报错：{', '.join(bad)}") if bad else (1.0, "无工具报错")


def _no_refusal(t: Trace) -> tuple[float, str]:
    low = t.output.lower()
    for m in REFUSAL_MARKERS:
        if m in low:
            return 0.0, f"命中拒答话术：{m}"
    return 1.0, "无拒答话术"


def _answers_expected_terms(t: Trace) -> tuple[float, str]:
    terms = t.meta.get("expected_terms") or []
    if not terms:
        return 1.0, "未声明期望要点（跳过）"
    out = t.output.lower()
    hit = [x for x in terms if x.lower() in out]
    return len(hit) / len(terms), f"命中 {len(hit)}/{len(terms)} 个期望要点"


def _within_budget(t: Trace) -> tuple[float, str]:
    cap = t.meta.get("max_steps")
    if not cap:
        return 1.0, "未设步数上限（跳过）"
    return (1.0, f"{t.steps}/{cap} 步") if t.steps <= cap else (0.0, f"超预算 {t.steps}/{cap} 步")


DEFAULT_RUBRIC: list[Criterion] = [
    Criterion("uses_tool", 0.20, _uses_tool),
    Criterion("no_tool_error", 0.25, _no_tool_error, fatal=True),
    Criterion("no_refusal", 0.15, _no_refusal, fatal=True),
    Criterion("answers_expected_terms", 0.30, _answers_expected_terms),
    Criterion("within_budget", 0.10, _within_budget),
]


@dataclass
class Judge:
    rubric: list[Criterion] = field(default_factory=lambda: list(DEFAULT_RUBRIC))
    threshold: float = 0.75

    def score(self, t: Trace) -> Verdict:
        total_w = sum(c.weight for c in self.rubric) or 1.0
        details: list[CriterionScore] = []
        acc = 0.0
        for c in self.rubric:
            raw, note = c.check(t)
            raw = max(0.0, min(1.0, float(raw)))
            details.append(CriterionScore(c.name, round(raw, 3), c.weight, note, c.kind))
            acc += raw * c.weight
        score = round(acc / total_w, 4)
        vetoed = [d.name for d in details if d.score == 0.0
                  and any(c.fatal and c.name == d.name for c in self.rubric)]
        return Verdict(case_id=t.case_id, score=score,
                       passed=(score >= self.threshold and not vetoed),
                       threshold=self.threshold, details=details, vetoed=vetoed)

    def score_all(self, traces: list[Trace]) -> list[Verdict]:
        return [self.score(t) for t in traces]
