"""一致性校准：机器 judge 只有在「跟人一致」之后才有资格接管评测。

Cohen's kappa 而不是裸一致率：如果 90% 的样本本来就是 PASS，
一个「全判 PASS」的裁判也有 90% 一致率，但它什么都没测出来。
"""
from __future__ import annotations

from dataclasses import dataclass


def cohen_kappa(a: list[bool], b: list[bool]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("labels 长度必须一致且非空")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1 = sum(a) / n
    pb1 = sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe == 1.0:
        # 两人标注都只有一种取值（全 PASS 或全 FAIL，n=1 也算）→ kappa 是 0/0，无定义。
        # 原实现返回 1.0，于是「恒定判 PASS」的裁判在 5 条全 PASS 上拿 kappa=1.0 并判达标 ——
        # 一个什么都没测的裁判拿到了合格证。退化就是退化，不给分。
        return 0.0
    return round((po - pe) / (1 - pe), 4)


def agreement(a: list[bool], b: list[bool]) -> float:
    return round(sum(1 for x, y in zip(a, b) if x == y) / len(a), 4)


MIN_CASES = 5   # 少于 5 条无法撑起一致性结论


@dataclass
class Calibration:
    n: int
    agreement: float
    kappa: float
    human_pass_rate: float
    judge_pass_rate: float
    min_kappa: float
    degenerate: bool = False
    min_cases: int = MIN_CASES

    @property
    def ok(self) -> bool:
        # 三个条件缺一不可：样本够、分布非退化、kappa 达标。
        return (not self.degenerate) and self.n >= self.min_cases and self.kappa >= self.min_kappa

    @property
    def diagnosis(self) -> str:
        if self.ok:
            return "judge 与人工标注一致性达标，可用于回归门禁"
        if self.degenerate:
            return f"标注分布退化（{self.n} 条里两人都只有一种取值）—— kappa 无判别力，不能当达标"
        if self.n < self.min_cases:
            return f"样本量不足（{self.n} < {self.min_cases}）—— 一致性结论撑不住，先补标注"
        if self.kappa < 0:
            return "judge 与人工标注系统性相反 —— rubric 方向写反了，先别上线"
        if self.judge_pass_rate > self.human_pass_rate + 0.2:
            return "judge 明显偏松（放过了人判为失败的样本），先收紧规则或补负例"
        if self.judge_pass_rate < self.human_pass_rate - 0.2:
            return "judge 明显偏严，会制造假告警，先放宽阈值或补正例"
        return "一致性不足且无明显偏置 —— 样本量太小或 rubric 表达不了这个判断"


def calibrate(human: dict[str, bool], judge: dict[str, bool], min_kappa: float = 0.6) -> Calibration:
    ids = sorted(set(human) & set(judge))
    if not ids:
        raise ValueError("human 与 judge 没有重叠的 case")
    a = [human[i] for i in ids]
    b = [judge[i] for i in ids]
    both_same_label = len(set(a) | set(b)) == 1
    return Calibration(
        n=len(ids), agreement=agreement(a, b), kappa=cohen_kappa(a, b),
        degenerate=both_same_label,
        human_pass_rate=round(sum(a) / len(a), 4), judge_pass_rate=round(sum(b) / len(b), 4),
        min_kappa=min_kappa,
    )
