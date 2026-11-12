"""报表：Markdown（发周报）+ 单文件 HTML（发客户链接）。

报表的第一屏必须是「我们 vs 竞品的差距」和「下一步该动哪个引用源」，
而不是一堆曲线。客户只为动作付钱。
"""
from __future__ import annotations

from .metrics import BrandStats, citation_share, gap_report, rank_distribution
from .models import Answer, Mention

HTML_CSS = """
:root{--ink:#111;--muted:#666;--line:#e6e6e6;--hot:#c0392b;--ok:#1e8449}
body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;
     color:var(--ink);max-width:960px;margin:40px auto;padding:0 20px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 8px;
     padding-bottom:6px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500}
.bar{height:8px;background:#eee;border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ink)}
.muted{color:var(--muted);font-size:13px}
.tag{font-size:12px;padding:1px 6px;border:1px solid var(--line);border-radius:10px}
"""


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def markdown_report(
    brand: str,
    category: str,
    competitors: list[str],
    stats: dict[str, BrandStats],
    mentions: list[Mention],
    answers: list[Answer],
    prompts_total: int,
) -> str:
    gap = gap_report(stats, brand, competitors)
    doms = citation_share(__import__("collections").Counter(
        {d: n for d, n in _dom_counter(answers).items()}))

    lines = [
        f"# {brand} · AI 可见性周报",
        "",
        f"- 品类：{category}",
        f"- 样本：{prompts_total} 条提示词 × {len({a.run_index for a in answers})} 次采样",
        f"- 竞品：{', '.join(competitors) if competitors else '（未设置）'}",
        "",
        "## 1. 我们站在哪",
        "",
        "| 品牌 | 提及次数 | 出现率 | 声量份额 | 平均位次 | 情感 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1].mentions):
        rate = s.prompts_seen / prompts_total if prompts_total else 0
        mark = " ←" if name == brand else ""
        lines.append(
            f"| {name}{mark} | {s.mentions} | {_pct(rate)} | {_pct(s.share_of_voice)} | "
            f"{s.avg_position} | {s.sentiment:+.2f} |"
        )
    if not stats:
        lines.append("| （无提及） | 0 | 0.0% | 0.0% | - | 0.00 |")

    lines += ["", "## 2. 差距", ""]
    if gap.get("gap_sov") is None:
        lines.append("没有可比的竞品数据，先补竞品清单。")
    else:
        lines.append(
            f"落后 **{gap['leader']}** 声量 **{_pct(gap['gap_sov'])}**、"
            f"出现率少 **{gap['gap_visibility']}** 条提示词、平均位次差 **{gap['gap_position']}** 位。"
        )

    lines += ["", "## 3. 位次分布（我们）", ""]
    dist = rank_distribution(mentions, brand)
    if dist:
        for pos, n in dist.items():
            lines.append(f"- 第 {pos} 位：{n} 次")
    else:
        lines.append("- 本周期一次都没被提到。")

    lines += ["", "## 4. AI 在引用谁（按域名）", ""]
    if doms:
        lines.append("| 域名 | 占比 |")
        lines.append("| --- | ---: |")
        for d, share in list(doms.items())[:15]:
            lines.append(f"| {d} | {_pct(share)} |")
    else:
        lines.append("无引用源。")

    lines += [
        "", "## 5. 下周该做的三件事", "",
        "1. 拿下引用占比最高但还没有我们页面的那个域名（投稿/评测/目录收录）。",
        "2. 针对「出现率最低但意图最靠购买」的 3 条提示词，补一页结构化对比内容。",
        "3. 抽查 5 条未被提及的回答，确认是产品事实缺失还是模型知识过期。",
        "",
        f"> 数据口径：提及 = 回答正文中品牌名的首次出现；声量份额 = 品牌提及数 / 全部品牌提及数。",
    ]
    return "\n".join(lines)


def _dom_counter(answers: list[Answer]):
    from collections import Counter
    c: Counter = Counter()
    for a in answers:
        for cit in a.citations:
            c[cit.domain] += 1
    return c


def html_report(md_title: str, body_sections: list[tuple[str, str]]) -> str:
    rows = []
    for title, html_table in body_sections:
        rows.append(f"<h2>{title}</h2>{html_table}")
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        f"<title>{md_title}</title><style>{HTML_CSS}</style>"
        f"<h1>{md_title}</h1>"
        "<p class='muted'>由 geo-radar 生成 · 口径见文末</p>"
        + "".join(rows)
        + "</html>"
    )
