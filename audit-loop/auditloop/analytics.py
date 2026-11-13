"""分析性程序（analytical procedures）：不看单笔凭证，看「比率和趋势是否自相矛盾」。

这是审计里最能抓到「收入被做高」的一类程序，因为它不需要逐笔抽凭：
收入涨 5%、应收账款涨 40%，两句话放在一起就说明有问题。
所有判断都**逐年**做（相邻两年一比），单年噪声靠阈值挡，不靠「连续两年」——
审计现场最常见的就是「某一年突然出现大背离」，要求连续两年才报会把最该看的那年漏掉。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Finding, VALUATION, EXISTENCE

# 阈值：都是「百分点」/ 比率，逐年判；单年波动由阈值本身过滤
RECEIVABLE_GAP_PP = 20.0      # 应收增速 - 收入增速
MARGIN_SHIFT_PP = 3.0         # 毛利率变动
CASH_CONVERSION_DROP = 0.10   # 经营现金流/收入 的绝对下滑
CASH_CONVERSION_DROP_REL = 0.25  # 或相对下滑 25%——两家收入规模不同，绝对阈值单用会漏


@dataclass
class Series:
    """某家公司的年度序列：{财年: 数值}。缺年不许插值，缺就报缺口。"""

    revenue: dict[int, float]
    receivables: dict[int, float] | None = None
    gross_profit: dict[int, float] | None = None
    cfo: dict[int, float] | None = None

    def years(self) -> list[int]:
        return sorted(self.revenue)


def _num(v: float | None) -> float | None:
    """把 None / 非数值挡在外面。

    导出表里某年缺列是常态；原实现让 None 一路进到除法，直接 TypeError，
    而同模块的 cash_conversion 又静默跳过 —— 同一份脏数据两种命运。
    """
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct(cur: float | None, prev: float | None) -> float | None:
    cur, prev = _num(cur), _num(prev)
    if cur is None or prev is None or not prev:
        return None
    return (cur - prev) / abs(prev) * 100


def revenue_vs_receivables(s: Series) -> list[Finding]:
    """收入与应收账款增速背离 —— 渠道压货/提前确认收入的经典信号。"""
    out: list[Finding] = []
    if not s.receivables:
        return out
    common = sorted(set(s.revenue) & set(s.receivables))
    for prev_y, cur_y in zip(common, common[1:]):
        rg = _pct(s.revenue.get(cur_y), s.revenue.get(prev_y))
        ag = _pct(s.receivables.get(cur_y), s.receivables.get(prev_y))
        if rg is None or ag is None:
            continue
        gap = ag - rg
        if gap > RECEIVABLE_GAP_PP:
            out.append(Finding(
                check="analytics.revenue_vs_receivables", assertion=EXISTENCE,
                ref=f"FY{cur_y}", severity="high" if gap > 2 * RECEIVABLE_GAP_PP else "medium",
                detail=(f"应收账款增速 {ag:+.1f}% 高于收入增速 {rg:+.1f}%（差 {gap:+.1f}pt），"
                        f"需检查是否存在提前确认收入或渠道压货"),
                amount=s.receivables[cur_y],
            ))
    return out


def gross_margin_trend(s: Series) -> list[Finding]:
    """毛利率突变：定价、成本结构或分类口径被改动。"""
    out: list[Finding] = []
    if not s.gross_profit:
        return out
    common = sorted(set(s.revenue) & set(s.gross_profit))
    margins = []
    for y in common:
        rev, gp = _num(s.revenue.get(y)), _num(s.gross_profit.get(y))
        if rev and gp is not None:
            margins.append((y, gp / rev * 100))
    for (py, pm), (cy, cm) in zip(margins, margins[1:]):
        shift = cm - pm
        if abs(shift) > MARGIN_SHIFT_PP:
            out.append(Finding(
                check="analytics.gross_margin_trend", assertion=VALUATION,
                ref=f"FY{cy}", severity="medium",
                detail=(f"毛利率由 FY{py} 的 {pm:.1f}% 变为 {cm:.1f}%（{shift:+.1f}pt），"
                        f"需确认成本归集与分类口径是否变化"),
            ))
    return out


def cash_conversion(s: Series) -> list[Finding]:
    """经营现金流/收入 下滑：利润没有变成现金。"""
    out: list[Finding] = []
    if not s.cfo:
        return out
    common = sorted(set(s.revenue) & set(s.cfo))
    ratios = []
    for y in common:
        rev, cfo = _num(s.revenue.get(y)), _num(s.cfo.get(y))
        if rev and cfo is not None:
            ratios.append((y, cfo / rev))
    for (py, pr), (cy, cr) in zip(ratios, ratios[1:]):
        absolute = pr - cr
        # 相对变化必须除 |pr|：pr<0 时（经营现金流为负）除以负数会把「改善」算成
        # 「+60% 下滑」。方向由 absolute 的正负决定，量级由 |pr| 归一。
        relative = absolute / abs(pr) if pr else 0.0
        dropped = absolute > 0
        if dropped and (absolute > CASH_CONVERSION_DROP or relative > CASH_CONVERSION_DROP_REL):
            out.append(Finding(
                check="analytics.cash_conversion", assertion=VALUATION,
                ref=f"FY{cy}", severity="medium",
                detail=(f"经营现金流/收入 由 {pr:.2f} 降至 {cr:.2f}"
                        f"（{relative:.0%} 相对下滑），利润的现金含量下降，需检查收入质量"),
                amount=s.cfo[cy],
            ))
    return out


def run_all(s: Series) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (revenue_vs_receivables, gross_margin_trend, cash_conversion):
        findings.extend(fn(s))
    return findings
