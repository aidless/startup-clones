"""小样本区间：bootstrap 百分位法。

来源：Inspect 的 `bootstrap_stderr()`（默认 1000 次重采样）与 `ci()` 的
`method="bootstrap"`（见 docs/BORROWED.md B-3）。这里不需要 SciPy：
提示词级的 0/1 序列做有放回重采样，取 2.5%/97.5% 分位即可。

固定 seed 是刻意的：同一批数据两次跑必须印出同一个区间，否则报表无法复核。
"""
from __future__ import annotations

import random
from collections.abc import Sequence


def bootstrap_ci(
    values: Sequence[float],
    level: float = 0.95,
    num_samples: int = 2000,
    seed: int = 12345,
) -> tuple[float, float]:
    """均值的 bootstrap 百分位区间。全等或空输入返回退化区间。"""
    if not values:
        return (0.0, 0.0)
    if len(set(values)) == 1:
        v = round(float(values[0]), 4)
        return (v, v)
    if not 0 < level < 1:
        raise ValueError(f"置信水平必须在 (0,1) 内，收到 {level}")

    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(num_samples))
    tail = (1 - level) / 2
    lo = means[int(tail * (num_samples - 1))]
    hi = means[int((1 - tail) * (num_samples - 1))]
    return (round(lo, 4), round(hi, 4))


def proportion_ci(
    successes: int,
    n: int,
    level: float = 0.95,
    num_samples: int = 2000,
    seed: int = 12345,
) -> tuple[float, float]:
    """k/n 的区间：把 0/1 序列交给 bootstrap，不做正态近似。"""
    if n <= 0:
        raise ValueError(f"样本量必须为正，收到 n={n}")
    if not 0 <= successes <= n:
        raise ValueError(f"成功数必须在 [0, n] 内，收到 {successes}/{n}")
    return bootstrap_ci(
        [1.0] * successes + [0.0] * (n - successes),
        level=level, num_samples=num_samples, seed=seed,
    )
