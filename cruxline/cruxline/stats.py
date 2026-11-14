"""小样本统计：区间估计与用例集指纹。

两个都借自外部成熟实现（来源与判据见 docs/BORROWED.md）：
- `wilson_interval` 对应 Inspect 的 `ci_wilson()`：二元得分的比例优先用 Wilson
  而不是正态近似，边界恒在 [0,1]，小样本与比例贴近 0/1 时仍校准。
- `set_fingerprint` 对应 Inspect eval-set 的稳定 sample id：只报通过率不报
  「量的是哪一批用例」，等于允许换一批用例也印出「涨了」。
"""
from __future__ import annotations

import hashlib
from statistics import NormalDist


def wilson_interval(successes: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """二元比例的 Wilson score 区间。n=0 或计数不可能时抛 ValueError。

    level 只影响 z；返回 (下界, 上界)，均已截到 [0, 1]。
    """
    if n <= 0:
        raise ValueError(f"样本量必须为正，收到 n={n}")
    if not 0 <= successes <= n:
        raise ValueError(f"成功数必须在 [0, n] 内，收到 {successes}/{n}")
    if not 0 < level < 1:
        raise ValueError(f"置信水平必须在 (0,1) 内，收到 {level}")

    z = NormalDist().inv_cdf(1 - (1 - level) / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, round(centre - half, 4)), min(1.0, round(centre + half, 4)))


def set_fingerprint(ids) -> str:
    """一批用例 id 的稳定指纹：与顺序无关，与成员有关。"""
    joined = "\n".join(sorted(str(i) for i in ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
