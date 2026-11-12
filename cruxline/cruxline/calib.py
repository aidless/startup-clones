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
        return 1.0 if po == 1.0 else 0.0
    return round((po - pe) / (1 - pe), 4)


def agreement(a: list[bool], b: list[bool]) -> float:
    return round(sum(1 for x, y in zip(a, b) if x == y) / len(a), 4)


@dataclass
class Calibration:
    n: int
    agreement: float
    kappa: float
    human_pass_rate: float
    judge_pass_rate: float
    min_kappa: float

    @property
    def ok(self) -> bool:
        return self.kappa >= self.min_kappa

    @property
    def diagnosis(self) -> str:
        if self.ok:
            return "judge 与人工标注一致性达标，可用于回归门禁"
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
    return Calibration(
        n=len(ids), agreement=agreement(a, b), kappa=cohen_kappa(a, b),
        human_pass_rate=round(sum(a) / len(a), 4), judge_pass_rate=round(sum(b) / len(b), 4),
        min_kappa=min_kappa,
    )
