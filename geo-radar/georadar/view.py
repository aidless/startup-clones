"""装载 / 装配：`run + mentions → stats → markdown` 的唯一入口。

此前两条命令各写一份拼 stats 的代码：

    cmd_run     : metrics.brand_stats(all_mentions, len(ps))       + 内存 answers
    cmd_report  : metrics.brand_stats(mentions, len(ids))          + 读库 answers

两份今天算出同一个数纯属分母碰巧相等（2026-11-13 store 主键修完之后复核过：
72 条提及 / 34.7% / 1.52）。谁改一处忘另一处，两份报表就会静默分叉，而且
分叉只体现在数字上，没有任何报错。

现在：两条命令都只负责「怎么拿到 run + mentions」，之后的装配一律进 `assemble()`。
`load_view()` 是读库侧的取数入口（内部只是 `store.load_run` + `assemble`）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import metrics, report, store
from .metrics import BrandStats
from .models import Answer, Mention, Run


@dataclass(frozen=True)
class RunView:
    """一次 run 的报表视图：报表需要的一切，一次装齐。"""

    run: Run
    stats: dict[str, BrandStats]
    mentions: list[Mention]
    answers: list[Answer]
    prompts_total: int

    @property
    def markdown(self) -> str:
        return report.markdown_report(
            self.run.brand, self.run.category, self.run.competitors,
            self.stats, self.mentions, self.answers, self.prompts_total,
        )


def assemble(run: Run, mentions: list[Mention]) -> RunView:
    """内存里的 run + mentions → 报表视图。

    分母 `prompts_total` 取「answers 里真实出现过的 prompt_id 条数」，不取
    「生成了多少条提示词」：没拿到回答的提示词不属于样本，算进分母会把出现率
    压低；而且两条路径原本正是这里不同（run 用 len(ps)，report 用 len(ids)）——
    只要有一次采样失败/提前中断，两份报表的分母就会当场对不上。
    """
    prompts_total = len({a.prompt_id for a in run.answers})
    return RunView(
        run=run,
        stats=metrics.brand_stats(mentions, prompts_total),
        mentions=list(mentions),
        answers=list(run.answers),
        prompts_total=prompts_total,
    )


def load_view(conn: Any, run_id: str) -> RunView:
    """从 SQLite 读回一次 run，装配成与内存路径同一个形状。"""
    run, mentions = store.load_run(conn, run_id)
    return assemble(run, mentions)
