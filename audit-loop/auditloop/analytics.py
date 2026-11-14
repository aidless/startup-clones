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
                        f"（{relative:.1%} 相对下滑），利润的现金含量下降，需检查收入质量"),
                amount=s.cfo[cy],
            ))
    return out


def run_all(s: Series) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (revenue_vs_receivables, gross_margin_trend, cash_conversion):
        findings.extend(fn(s))
    return findings


# ---------------- 逐年明细（CLI 的「指标 / 本期 / 上期 / 变化 / 判定」行） ----------------
#
# 上面三个程序只吐「例外」，看不出「这一年到底算出了什么数」。命令行要的是
# 一张逐年明细表，所以这里把**同一个指标**在相邻两年的取值摊开成一条记录：
# current/prior 都指这个指标本身（例如收入应收增速差取的是「差值」），
# change = current - prior。文本与 --json 都从这一条记录渲染，
# 两边不会各算一遍，也就不会出现数字口径不一致。

_PRECISION = {"pp": 1, "%": 1, "x": 2}


@dataclass
class Item:
    name: str               # 程序键，与 Finding.check 的后半段一致
    label: str              # 中文指标名
    ref: str                # 本期财年（"2026"），数据不足时为空
    prior_ref: str          # 上期财年，首年为空
    current: float | None
    prior: float | None
    change: float | None
    unit: str               # pp（百分点）| % | x（比率）
    status: str             # ok | flag | insufficient
    severity: str = ""
    detail: str = ""

    @property
    def flag(self) -> bool:
        return self.status == "flag"

    def as_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label,
            "ref": self.ref, "prior_ref": self.prior_ref,
            "current": self.current, "prior": self.prior, "change": self.change,
            "unit": self.unit, "status": self.status, "flag": self.flag,
            "severity": self.severity, "detail": self.detail,
        }


def _round(v: float | None, unit: str) -> float | None:
    if v is None:
        return None
    # + 0.0 把 -0.0 归一成 0.0，否则文本会印出 "-0.00"
    return round(v, _PRECISION[unit]) + 0.0


def _consecutive(values: dict[int, float]) -> list[tuple[int, int]]:
    years = sorted(values)
    return list(zip(years, years[1:]))


def revenue_gap_series(s: Series) -> dict[int, float]:
    """{财年: 应收增速 - 收入增速}，单位百分点。"""
    if not s.receivables:
        return {}
    out: dict[int, float] = {}
    common = sorted(set(s.revenue) & set(s.receivables))
    for prev_y, cur_y in zip(common, common[1:]):
        rg = _pct(s.revenue.get(cur_y), s.revenue.get(prev_y))
        ag = _pct(s.receivables.get(cur_y), s.receivables.get(prev_y))
        if rg is None or ag is None:
            continue
        out[cur_y] = ag - rg
    return out


def margin_series(s: Series) -> dict[int, float]:
    """{财年: 毛利率%}。"""
    if not s.gross_profit:
        return {}
    out: dict[int, float] = {}
    for y in sorted(set(s.revenue) & set(s.gross_profit)):
        rev, gp = _num(s.revenue.get(y)), _num(s.gross_profit.get(y))
        if rev and gp is not None:
            out[y] = gp / rev * 100
    return out


def cash_ratio_series(s: Series) -> dict[int, float]:
    """{财年: 经营现金流/收入}。"""
    if not s.cfo:
        return {}
    out: dict[int, float] = {}
    for y in sorted(set(s.revenue) & set(s.cfo)):
        rev, cfo = _num(s.revenue.get(y)), _num(s.cfo.get(y))
        if rev and cfo is not None:
            out[y] = cfo / rev
    return out


def _items(values: dict[int, float], *, name: str, label: str, unit: str,
           check: str, findings: list[Finding]) -> list[Item]:
    """把逐年指标摊成逐项 Item；判定与 detail 直接复用 run_all 的 Finding。

    判定不在这里另写一套阈值 —— 否则 CLI 与程序本身迟早给出相反的结论
    （正是审查里 P1-d 那类「注释与实现不一致」的近亲）。
    """
    idx = {(f.check, f.ref): f for f in findings}
    years = sorted(values)
    out: list[Item] = []
    for i, y in enumerate(years):
        prev_y = years[i - 1] if i else None
        cur = values[y]
        prior = values[prev_y] if prev_y is not None else None
        f = idx.get((check, f"FY{y}"))
        out.append(Item(
            name=name, label=label, ref=str(y),
            prior_ref=str(prev_y) if prev_y is not None else "",
            current=_round(cur, unit), prior=_round(prior, unit),
            change=_round(cur - prior, unit) if prior is not None else None,
            unit=unit, status="flag" if f else "ok",
            severity=f.severity if f else "", detail=f.detail if f else "",
        ))
    return out


def assess(s: Series) -> list[Item]:
    """三条分析性程序的逐年明细。

    算不出来的程序返回**一条 insufficient 记录**而不是空清单：空清单与
    「跑了且没问题」在输出上完全一样（README 已知边界点过这一条），
    命令行必须把「没查」说出来。
    """
    findings = run_all(s)
    specs = (
        ("revenue_vs_receivables", "应收增速差", "pp",
         "analytics.revenue_vs_receivables", revenue_gap_series(s)),
        ("gross_margin", "毛利率", "%", "analytics.gross_margin_trend", margin_series(s)),
        ("cash_conversion", "现金含量", "x", "analytics.cash_conversion", cash_ratio_series(s)),
    )
    out: list[Item] = []
    for name, label, unit, check, values in specs:
        out.extend(_items(values, name=name, label=label, unit=unit,
                          check=check, findings=findings)
                   or [Item(name=name, label=label, ref="", prior_ref="",
                            current=None, prior=None, change=None, unit=unit,
                            status="insufficient")])
    return out


def series_from_years(years: object) -> Series:
    """把 facts JSON 的 {"2026": {"revenue": ...}} 转成 Series。

    每列独立收：导出表整列缺失是常态，一列没有不该拖垮另外两列。
    只有收入一列为空算输入错误 —— 三条程序全以收入为基准，没收入什么也算不出来。
    """
    if not isinstance(years, dict) or not years:
        raise ValueError("facts 里没有 years 对象")

    def col(key: str) -> dict[int, float]:
        out: dict[int, float] = {}
        for raw_year, row in years.items():
            if not isinstance(row, dict):
                continue
            try:
                year = int(raw_year)
            except (TypeError, ValueError):
                raise ValueError(f"财年不是整数：{raw_year!r}") from None
            v = _num(row.get(key))
            if v is not None:
                out[year] = float(v)
        return out

    revenue = col("revenue")
    if not revenue:
        raise ValueError("years 里没有任何 revenue 数字")
    return Series(revenue=revenue,
                  receivables=col("receivables") or None,
                  gross_profit=col("gross_profit") or None,
                  cfo=col("cfo") or None)
