"""借用外部机制：小样本比例必须带区间（来源见 docs/BORROWED.md B-3）。

来源：Inspect 的 bootstrap_stderr()（默认 1000 次重采样）。
本项目的样本是「32 次模型采样」，34.7% 这个数字在 N=32 下的 95% 区间能盖住
三个十个百分点 —— 不印区间就是在给客户一个他无法复算的精确值。
"""
from __future__ import annotations

import re

from georadar import metrics, report
from georadar.models import Answer, Mention
from georadar.stats import bootstrap_ci, proportion_ci


def test_proportion_ci_is_deterministic():
    assert proportion_ci(11, 32) == proportion_ci(11, 32)


def test_proportion_ci_brackets_observed_value():
    lo, hi = proportion_ci(11, 32)
    assert lo < 11 / 32 < hi
    assert hi - lo > 0.15          # N=32 时区间本就该宽，收窄就是假精确


def test_ci_narrows_with_more_samples_at_same_rate():
    wide = proportion_ci(11, 32)
    narrow = proportion_ci(110, 320)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0]) / 2


def test_bootstrap_ci_handles_degenerate_inputs():
    assert bootstrap_ci([]) == (0.0, 0.0)
    assert bootstrap_ci([1.0]) == (1.0, 1.0)
    assert bootstrap_ci([0.0, 0.0, 0.0]) == (0.0, 0.0)


def test_report_prints_interval_next_to_appearance_rate():
    mentions = [
        Mention(prompt_id=f"p{i}", brand="Acme", position=1, char_offset=0,
                sentiment=0.5, run_index=0)
        for i in range(3)
    ] + [
        Mention(prompt_id=f"p{i}", brand="Beta", position=2, char_offset=0,
                sentiment=0.0, run_index=0)
        for i in range(6)
    ]
    stats = metrics.brand_stats(mentions, prompts_total=8)
    answers = [Answer(prompt_id=f"p{i}", provider="p", model="m", text="", run_index=0)
               for i in range(8)]
    md = report.markdown_report("Acme", "AI SRE", ["Beta"], stats, mentions, answers, 8)
    assert re.search(r"\d+\.\d% \[\d+\.\d%, \d+\.\d%\]", md), md
    assert "bootstrap" in md.lower(), md
