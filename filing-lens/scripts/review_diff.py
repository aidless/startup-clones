#!/usr/bin/env python3
"""生成「10-K 复核差异表」——卖给事务所的那一页纸。

六项固定检查（口径见 samples/prospects/README.md），每项要么给出可追的 ref，
要么明确写「无法核」。绝不猜：宁可少一条，不可多一条假警报。

用法：
    python3 scripts/review_diff.py 0000320193              # 用 data/ 里的语料
    python3 scripts/review_diff.py 0000320193 --out x.md
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens import corpus, facts, ingest  # noqa: E402
from filinglens.answer import RESPECTIVELY_RE, headcount_number  # noqa: E402

# 「$145.10 billion」/「36.3B」/「1,204.3 million」
_MONEY = re.compile(
    r"\$?\s?([0-9][0-9,]*\.?[0-9]*)\s*(billion|million|B\b|M\b|trillion)", re.I)
# 小盘 10-K 常年按整元记账、不带量级词（PAID INC 原文 "$ 20,690,000"）。只认带
# million/billion 的写法时，这类公司整份 10-K 的金额一个都读不到 —— 检查照跑、结论
# 是「正文没有同量级表述」，对小盘客户（我们的全部目标客户）等于空转。
_MONEY_PLAIN = re.compile(r"\$\s?([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?)")
_SCALE = {"billion": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "trillion": 1e12}
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")

CASH_TAG = "CashAndCashEquivalentsAtCarryingValue"
# 不少小盘公司在某个年度之后改用「含受限现金」的合并标签。只认前一个标签时，
# `_latest` 会取到好几年前的余额，再和今年的经营现金流相减（XERIANT 实测：
# 2026 的 CFO 减 2021 的现金，印出「差 1.8×」，两个年份的数相减没有含义）。
CASH_TAGS = (CASH_TAG,
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
CFO_TAG = "NetCashProvidedByUsedInOperatingActivities"
REV_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")


@dataclass
class Finding:
    check: str
    what: str
    ref: str
    action: str
    severity: str = "info"          # info / look / mismatch
    doubt: str = ""                 # 我们自己不确定的地方，照实写


@dataclass
class Report:
    cik: str
    entity: str = ""
    period: str = ""
    findings: list[Finding] = field(default_factory=list)
    injected: tuple[str, str] | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)


def _money_values(text: str) -> list[tuple[float, str]]:
    out = []
    for m in _MONEY.finditer(text):
        raw, unit = m.group(1), m.group(2).lower().rstrip(".")
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        out.append((v * _SCALE.get(unit, 1.0), m.group(0).strip()))
    for m in _MONEY_PLAIN.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append((v, m.group(0).strip()))
    return out


def _latest(conn, tag: str) -> facts.Fact | None:
    rows = conn.execute(
        "SELECT tag, fy, val, unit, form, end FROM facts WHERE tag=? AND unit LIKE 'USD%' "
        "ORDER BY fy DESC, end DESC LIMIT 1", (tag,)).fetchall()
    return facts.Fact(**dict(rows[0])) if rows else None


def _latest_at(conn, tags: tuple[str, ...], fy: int) -> tuple[facts.Fact, str] | None:
    """只取指定财年的那一行，并返回命中的标签（标签名要写进出处）。"""
    for tag in tags:
        rows = conn.execute(
            "SELECT tag, fy, val, unit, form, end FROM facts "
            "WHERE tag=? AND fy=? AND unit LIKE 'USD%' ORDER BY end DESC LIMIT 1",
            (tag, fy)).fetchall()
        if rows:
            return facts.Fact(**dict(rows[0])), tag
    return None


def _series(conn, tag: str) -> list[facts.Fact]:
    return facts.annual_series(conn, tag) if conn else []


def _sents(chunks, keyword: str, limit: int = 400):
    """只在含关键词的段落里切句，避免扫全文。"""
    key = keyword.lower()
    seen = 0
    for ch in chunks:
        if key not in ch.text.lower():
            continue
        for s in _SENT_SPLIT.split(ch.text):
            if key in s.lower():
                yield s.strip(), ch.ref
                seen += 1
                if seen >= limit:
                    return


def check_cash_caliber(f: corpus.Filing, rep: Report) -> None:
    """1. 现金流量口径：正文说 operating cash flow 时，数字对的是哪个科目。"""
    cfo = _latest(f.conn, CFO_TAG)
    if not cfo:
        rep.skipped.append(("现金流量口径", f"facts 里缺 {CFO_TAG}"))
        return
    hit = _latest_at(f.conn, CASH_TAGS, cfo.fy)
    if not hit:
        rep.skipped.append((
            "现金流量口径",
            f"经营现金流 FY{cfo.fy} 有值，但同年没有现金及等价物标签"
            f"（查过 {len(CASH_TAGS)} 个标签名）；不同年份的余额与流量相减得到的倍数没有含义，"
            f"所以不做跨年比较"))
        return
    cash, cash_tag = hit
    # 不再印「差 N×」：经营现金流是期间流量、现金及等价物是期末存量，
    # 两者相除既不是覆盖率也不是周转率（XERIANT 印出「差 10.0×」，只会让人以为算错了）。
    rep.add(Finding("现金流量口径",
                    f"两个科目都在：经营现金流 FY{cfo.fy} = {facts.fmt_money(cfo.val)}"
                    f"（期间流量），现金及等价物 FY{cash.fy} = {facts.fmt_money(cash.val)}"
                    f"（期末存量）",
                    f"XBRL:{CFO_TAG}@{cfo.fy} / XBRL:{cash_tag}@{cash.fy}",
                    "正文若用「cash flow」「cash generated」指前者，注意别被后者的标签带偏",
                    "look"))
    # 只在「金额直接跟在科目名后面」时判：Broadcom 的
    # "Cash and cash equivalents increased to $16,178 million ... primarily due to
    #  $27,537 million in net cash provided by operating activities"
    # 一句里同时出现余额与流量，按「句中有 operating 就取第一个金额」会把它判成口径混淆
    # （第一版实测就是这么误报的）。要判必须精确绑定到科目名。
    # 两种语序都要认：
    #   ① 数在前 —— "due to $27,537 million in net cash provided by operating activities"（Broadcom 原文）
    #   ② 数在后 —— "operating cash flow was $145.1 billion"
    # 只写一种语序等于这道检查整项空转（第一版就是：Broadcom 那句因为数在前，
    # 正则一次都没命中，看着「零误报」其实是没在测）。
    _PHRASE = r"(?:operating cash flow|cash (?:provided by|generated by|from) operating activities)"
    pats = (
        re.compile(r"\$?\s?([0-9][0-9,]*\.?[0-9]*)\s*(billion|million)[^.$]{0,30}?" + _PHRASE, re.I),
        re.compile(_PHRASE + r"[^.$]{0,24}?\$?\s?([0-9][0-9,]*\.?[0-9]*)\s*(billion|million)", re.I),
    )
    hits = 0
    for sent, ref in _sents(f.chunks, "operating"):
        for pat in pats:
            for m in pat.finditer(sent):
                val = float(m.group(1).replace(",", "")) * _SCALE[m.group(2).lower()]
                near_cash = abs(val - cash.val) / max(cash.val, 1) < 0.02
                near_cfo = abs(val - cfo.val) / max(cfo.val, 1) < 0.02
                if near_cash and not near_cfo:
                    rep.add(Finding("现金流量口径",
                                    f"正文把 {m.group(0).strip()} 说成经营现金流，"
                                    f"但这个数与「现金及等价物」一致（{facts.fmt_money(cash.val)}），"
                                    f"与经营现金流（{facts.fmt_money(cfo.val)}）不一致",
                                    ref,
                                    "确认这里是流量还是余额；主语若是余额，措辞不该用 operating cash flow",
                                    "mismatch"))
                    hits += 1
                break
            if hits >= 3:
                return


def check_headcount_year(f: corpus.Filing, rep: Report) -> None:
    """2. 员工数：句子里同时有人数与年份时，年份不能当人数。"""
    hits = 0
    for sent, ref in _sents(f.chunks, "employee"):
        if not re.search(r"\bemployees?\b", sent, re.I):
            continue
        naive = RESPECTIVELY_RE.search(sent)
        if not naive:
            continue
        got = headcount_number(sent)
        raw = naive.group(1)
        if got is None or got != raw:
            rep.add(Finding("员工数",
                            f"此句含两个数字并列 + employees，naive 取法会读成「{raw} 人」，"
                            f"实际这里的数字是年份/期间",
                            ref,
                            "核对人数时用带上下文的读法，别按「数字 + employees」直接取",
                            "look"))
            hits += 1
        if hits >= 3:
            break
    if hits == 0:
        # 没踩到年份陷阱也要把人数的原文报出来——这是复核员要核对的第一手事实
        for sent, ref in _sents(f.chunks, "employees", limit=80):
            if not re.search(r"\bemployees?\b", sent, re.I):
                continue
            got = headcount_number(sent)
            if got:
                rep.add(Finding("员工数", f"正文披露员工数 {got}（原句已核对：不是年份）",
                                ref, "与审计底稿/上年披露核对人数与口径（FTE 还是总人数）", "info"))
                break
        else:
            # 办学/医疗类公司不一定用 "employees"，但人数照样在正文里披露
            # （Legacy Education 原文：「we had approximately 120 full-time faculty …」）。
            # 只扫含 employees 的句子会把这句判成「没有披露」，等于漏掉一手事实。
            alt = re.compile(
                r"\b(?:approximately\s+|about\s+|over\s+)?([0-9][0-9,]{0,6})\s+"
                r"(?:full-time\s+|part-time\s+|full time\s+|part time\s+)?"
                r"(faculty|staff|personnel|team members|associates|workers)\b", re.I)
            for sent, ref in _sents(f.chunks, "faculty", limit=40):
                m = alt.search(sent)
                if m:
                    rep.add(Finding("员工数",
                                    f"正文披露 {m.group(1)} 名 {m.group(2)}"
                                    f"（不是 employees 口径，核对时注意 FTE/兼职是否分开算）",
                                    ref, "与底稿人数及上年披露核对口径（FTE / 全职 / 兼职）",
                                    "info"))
                    break
            else:
                rep.skipped.append(("员工数", "本份 10-K 未出现含 employees/faculty/staff 的人数句式"))


def check_yoy_negative_base(f: corpus.Filing, rep: Report) -> None:
    """3. 同比：负基数上的百分比变化没有经济含义。"""
    for tag, label in ((CFO_TAG, "经营现金流"), (REV_TAGS[0], "营业收入")):
        s = _series(f.conn, tag)
        if len(s) < 2:
            continue
        prev, cur = s[-2], s[-1]
        if prev.val < 0 and cur.val < 0:
            pct = (cur.val - prev.val) / abs(prev.val) * 100
            rep.add(Finding("同比口径",
                            f"{label} {prev.fy} = {facts.fmt_money(prev.val)}、"
                            f"{cur.fy} = {facts.fmt_money(cur.val)}：都是负数，"
                            f"按绝对值算「变化 {pct:+.1f}%」，这个百分比没有经济含义",
                            f"XBRL:{tag}@{prev.fy}→@{cur.fy}",
                            "正文若给出百分比变化，核对它是按绝对值还是按带符号基数算的",
                            "look"))
        elif (prev.val > 0) != (cur.val > 0):
            # 基数跨零：447,643 → -53,171 按公式算得出 -111.9%，但这个数没有任何含义
            # （正文也不会这么写），照抄给复核员去「核对」，等于让他白跑一趟。
            rep.add(Finding("同比口径",
                            f"{label} {prev.fy} = {facts.fmt_money(prev.val)}、"
                            f"{cur.fy} = {facts.fmt_money(cur.val)}：基数跨零"
                            f"（由{'正转负' if prev.val > 0 else '负转正'}），"
                            f"百分比变化无含义，只能看绝对额",
                            f"XBRL:{tag}@{prev.fy}→@{cur.fy}",
                            "核对正文是怎么描述这次变化的（通常写「转为净流出」而不是百分比）",
                            "look"))
        elif prev.val > 0:
            pct = (cur.val - prev.val) / prev.val * 100
            rep.add(Finding("同比口径",
                            f"{label} {prev.fy} → {cur.fy}：{pct:+.1f}%"
                            f"（{facts.fmt_money(prev.val)} → {facts.fmt_money(cur.val)}）",
                            f"XBRL:{tag}@{prev.fy}→@{cur.fy}",
                            "与正文披露的百分比核对一次",
                            "info"))


def check_segments(f: corpus.Filing, rep: Report) -> None:
    """4. 分部加总：只有 facts 里真有 segment 维度才核，否则照实说无法核。"""
    tags = [r[0] for r in f.conn.execute(
        "SELECT DISTINCT tag FROM facts WHERE tag LIKE '%Segment%' LIMIT 5").fetchall()]
    if not tags:
        rep.skipped.append(("分部/地区加总", "本份 companyfacts 无 segment 维度，跳过"))
        return
    rep.add(Finding("分部加总", f"facts 里有 segment 相关标签：{', '.join(tags[:3])}",
                    "XBRL:segment", "需人工按分部取值相加后与合计比对", "info"))


# 只认「increased/decreased … N%」这种同比句式。
# 第一版把方向词写成可选，结果 "accounted for approximately 60% of total net sales"、
# "fines up to 10%" 全被当成同比差异报了出来（Apple 实测两条假阳）——
# 复核员看到一条假警报就不会再打开第二页，这条正则宁可漏也不能错。
# 三种写法都要认：动词式「increased 12%」、名词式「an increase of 12%」、口语式「up 12%」。
# 只认动词式时，「Total revenue was $63.3 billion, an increase of 12%」这类最常见的
# MD&A 写法一个都不命中——检查照跑、结论「未用百分比表述」，等于把主力句式静默丢掉。
_PCT = re.compile(
    r"\b(?:increased|decreased|grew|declined|rose|fell)\b[^.%]{0,30}?(\d{1,3}(?:\.\d+)?)\s*%"
    r"|\b(?:an?\s+)?(?:increase|decrease|growth|decline|reduction)\s+of\s+(\d{1,3}(?:\.\d+)?)\s*%"
    r"|\b(?:up|down)\s+(\d{1,3}(?:\.\d+)?)\s*%", re.I)
# 合计口径的主语。原件写「Total net sales」「Net sales」「Total revenue」「revenues」都算，
# 但「Services net sales」「Product net sales」这类带分部修饰的不算 —— 只看这几组词会
# 把 Tesla 的「Services net sales decreased $770 million, or 28%」判成合计同比（实测假阳）。
# 只认**自带合计含义**的主语：total/net sales、total/net revenue、consolidated ...
# 光写 "revenue" 不行 —— 「RL revenue in 2025 increased $61 million, or 3%」里的 RL 是
# Reality Labs 分部，句子结构与合计口径一模一样（实测假阳）。宁可漏掉不带限定词的
# 写法，也不给合伙人递一条假警报。
_TOTAL_SUBJECT = re.compile(
    r"\b(?:total|consolidated|company-?wide|net)\s+(?:net\s+)?(?:sales|revenues?)\b", re.I)
# 主语前面紧邻这些词 → 说明是分部/产品/地区口径，不是合计。
_CATEGORY_PREFIX = re.compile(
    r"\b(?:services?|products?|advertising|segment|geograph\w*|Americas|EMEA|APJC"
    r"|region\w*|division\w*|subscription\w*|hardware|software|cloud|other|devices?"
    r"|mobility|platforms?|solutions?)\s*$", re.I)
_PCT_EXCLUDE = re.compile(
    r"%\s*of\b|\bof (?:total|net sales|revenue)\b"
    # 「increased from 53.4% to 53.6%」讲的是费用率/毛利率的水平变化，不是营收同比。
    r"|\bfrom\s+\d[\d.]*\s*%\s+to\b", re.I)


# 季度/环比的句子不进年度同比比对：Cisco「For the fourth quarter ... total revenue
# increased by 18%」与 Meta「increased 17%, 19%, 17% between the third and fourth
# quarters」都是期间口径不同，拿来比全年同比是绑错对象（2026-11-14 语料普查实测）。
_QUARTER_RE = re.compile(
    r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarters?\b"
    r"|\bquarterly\b|\bQ[1-4]\b|\bsequential\w*|\bquarter-over-quarter\b", re.I)
# 主语与百分比之间若出现这些词，说明百分比说的是别的东西（分部/产品/地区）。
_OTHER_SUBJECT = re.compile(
    r"\b(?:product|service|services|segment|geograph\w*|Americas|EMEA|APJC|region\w*"
    r"|division\w*|subscri\w+|advertising|revenue|revenues|sales)\b", re.I)


def _pct_value(m: re.Match) -> float:
    """三种写法各占一组，取第一个非空组。"""
    for g in m.groups():
        if g:
            return float(g)
    return 0.0


# 允许出现在合计主语前面的限定词（大写开头但不算分部名）。
_DETERMINERS = {"total", "consolidated", "net", "our", "the", "in", "for", "during",
                "company", "its", "and", "while", "fiscal", "as"}


def _segment_prefix(before: str) -> bool:
    """主语前面紧邻的词里有大写词 → 说明是分部/产品名在修饰这个主语。"""
    words = re.findall(r"[A-Za-z][A-Za-z&.\-]*", before)[-3:]
    for w in words:
        if w[:1].isupper() and w.lower() not in _DETERMINERS:
            return True
    return False


def _quarter_scoped(sent: str, pct_start: int) -> bool:
    """这个百分比是不是在讲季度/环比。

    整句一刀切会把「Revenues increased $2,122,710 or 11% in 2025 primarily from a
    result of the fourth quarter increase in shipping…」误杀（PAID INC 实测）——
    这里的 quarter 讲的是收入来源，不是期间。所以按位置判：
    · 句子开头 45 字内出现季度词 → 期间限定整句（Cisco「For the fourth quarter … 18%」）；
    · 百分比前 40 字内出现季度词 → 就近限定（「… in the fourth quarter increased 18%」）；
    · 句子里有多个百分比并列 → 是逐季度/逐期枚举（Meta「17%, 19%, and 17%」）。
    """
    head = sent[:45]
    if _QUARTER_RE.search(head):
        return True
    if _QUARTER_RE.search(sent[max(0, pct_start - 40):pct_start]):
        return True
    return bool(_MULTI_PCT_LIST.search(sent))


# 「17%, 19%, and 17%」——多个百分比并列＝逐期枚举，不是一次全年同比。
_MULTI_PCT_LIST = re.compile(r"\d(?:[.,]\d+)?\s*%\s*(?:,\s*(?:and\s+)?|and\s+)\d")


def _money_delta_matches(sent: str, delta: float) -> bool:
    """句子里写出的金额增量，是否就是 XBRL 算出的当年增量。

    小盘 MD&A 常写「Revenues increased $2,122,710 or 11%」——主语不带 total/net，
    但增量金额能对上 XBRL，就足以证明它讲的是合计口径（PAID INC 实测）。
    这是**补充**判据：主语自带合计含义时不用它，避免与分部数字撞上。
    """
    if not delta:
        return False
    tol = max(1.0, abs(delta) * 0.02)
    return any(abs(abs(val) - abs(delta)) <= tol for val, _raw in _money_values(sent))


def _pct_bound_to_total(sent: str, pct_start: int) -> bool:
    """百分比是否**紧接**在合计主语后面（中间只有动词/数字/标点）。

    只判「句子里有没有 total revenue」不够：Cisco 那句
    「Within total revenue, product revenue increased by 16%」里 total 与 16% 都在，
    但百分比属于 product revenue。判据是主谓之间不许插进另一个主语。
    """
    for m in _TOTAL_SUBJECT.finditer(sent):
        if m.end() > pct_start:
            continue
        gap = sent[m.end():pct_start]
        if len(gap) > 80:
            continue
        if _OTHER_SUBJECT.search(gap):
            continue
        # 主语前是否被分部词修饰：「Services net sales」「Data Center net revenue」
        # 「RL revenue」。分部名多为多个大写词，列表永远列不全，所以判据是
        # 「紧邻的大写词不是限定词」而不是「命中某个已知分部名」。
        if _segment_prefix(sent[:m.start()]):
            continue
        return True
    return False


def check_text_percent(f: corpus.Filing, rep: Report) -> None:
    """正文给的百分比 vs 用 XBRL 实算的百分比。

    大多数 10-K 的 MD&A 不写绝对金额、只写「increased 15%」——
    按金额比对的检查会整项落空（Apple 实测），所以百分比这一项是主力。
    """
    for tag, label, keys in ((REV_TAGS[0], "营业收入", ("net sales", "revenue")),
                             (CFO_TAG, "经营现金流", ("cash provided by operating", "operating cash flow"))):
        series = _series(f.conn, tag)
        if len(series) < 2:
            continue
        prev, cur = series[-2], series[-1]
        if prev.val == 0:
            continue
        if (prev.val > 0) != (cur.val > 0):
            # 基数跨零时百分比没有含义（447,643 → -53,171 算得 -111.9%）。
            # 拿这个数去否定正文的「decreased」，是用坏尺判客户错（PAID INC 实测）。
            rep.skipped.append((f"正文百分比（{label}）",
                                f"{prev.fy}→{cur.fy} 基数跨零"
                                f"（{facts.fmt_money(prev.val)} → {facts.fmt_money(cur.val)}），"
                                f"百分比不可比，本项不做比对"))
            continue
        actual = (cur.val - prev.val) / abs(prev.val) * 100
        found = 0
        for sent, ref in _sents_multi(f.chunks, keys, limit=200):
            if "fiscal" in sent.lower() and "%" not in sent:
                continue
            if _PCT_EXCLUDE.search(sent):
                continue
            # 主语自带合计含义（total/net sales…）→ 必须绑到那个主语；
            # 主语只是裸的 revenues/sales → 只有当句中金额增量与 XBRL 一致时才认。
            # Meta 的「Services net sales decreased $770 million, or 28%」属第一种但绑不上，
            # 直接丢掉（拿分部比总营收会产生 12 条假阳，实测）。
            subject_bound = _TOTAL_SUBJECT.search(sent) is not None
            for m in _PCT.finditer(sent):
                if _quarter_scoped(sent, m.start()):
                    continue
                if subject_bound:
                    if not _pct_bound_to_total(sent, m.start()):
                        continue
                elif not _money_delta_matches(sent, cur.val - prev.val):
                    continue
                claimed = _pct_value(m)
                if abs(claimed - abs(actual)) <= 1.0:
                    rep.add(Finding("正文百分比",
                                    f"正文称「{m.group(0).strip()}」，XBRL 实算 {actual:+.1f}% —— 一致",
                                    ref, "无需动作；此条用于证明核对覆盖到了这一处", "info"))
                    found += 1
                    break
                if abs(claimed - abs(actual)) >= 3.0 and claimed >= 1:
                    rep.add(Finding("正文百分比",
                                    f"正文称「{m.group(0).strip()}」，XBRL 实算 {actual:+.1f}%"
                                    f"（{facts.fmt_money(prev.val)} → {facts.fmt_money(cur.val)}）",
                                    ref,
                                    "确认这里的百分比口径（同比期、汇率不变口径、还是分部口径）",
                                    "mismatch"))
                    found += 1
                    break
            if found >= 2:
                break
        if not found:
            rep.skipped.append((f"正文百分比（{label}）",
                                f"正文未用百分比表述该指标（XBRL 实算 {actual:+.1f}%）"))


def _sents_multi(chunks, keys, limit: int = 200):
    """多个关键词的句子合并扫描，按 ref 去重。"""
    seen: set[tuple[str, str]] = set()
    out = 0
    for key in keys:
        for sent, ref in _sents(chunks, key, limit=limit):
            tagk = (sent[:80], ref)
            if tagk in seen:
                continue
            seen.add(tagk)
            yield sent, ref
            out += 1
            if out >= limit:
                return


def check_text_vs_xbrl(f: corpus.Filing, rep: Report) -> None:
    """5. 同一指标在正文与 XBRL 的取值是否一致（含四舍五入与措辞）。

    按段落扫而不是按句扫：MD&A 里的数字常在长段中间，逐句切会把数字切丢
    （Apple 实测：按句扫 8 段 "net sales" 句里一个金额都没有）。
    """
    for tag, label, keys in ((REV_TAGS[0], "营业收入", ("revenue", "net sales")),
                             ("NetIncomeLoss", "净利润", ("net income",))):
        latest = _latest(f.conn, tag)
        if not latest:
            continue
        near, exact, samples = 0, 0, []
        for ch in f.chunks:
            low = ch.text.lower()
            if not any(k in low for k in keys):
                continue
            for val, raw in _money_values(ch.text):
                if abs(val - latest.val) / max(latest.val, 1) < 0.02:
                    near += 1
                    if abs(val - latest.val) < 1.0:
                        exact += 1
                    if len(samples) < 3:
                        samples.append((raw, ch.ref))
                    break
        if near:
            rep.add(Finding("正文与 XBRL",
                            f"{label} FY{latest.fy}：XBRL = {facts.fmt_money(latest.val)}；"
                            f"正文 {near} 个段落里出现同量级数字（{exact} 个与 XBRL 精确相等），"
                            f"样例 {samples[0][0]}",
                            samples[0][1],
                            "抽查这几个段落的措辞（approximately / 精确值）与 XBRL 口径是否一致",
                            "info"))
        else:
            rep.skipped.append((f"正文与 XBRL（{label}）",
                                f"正文没有与 XBRL 值 {facts.fmt_money(latest.val)} 同量级的表述"))


def _risk_paragraphs(f: corpus.Filing) -> list[str]:
    """Item 1A 里的正文段落（按空行切，短于 60 字的碎片丢掉）。"""
    out: list[str] = []
    for c in f.chunks:
        if "item 1a" not in c.ref.lower():
            continue
        for para in re.split(r"\n\s*\n", c.text):
            p = " ".join(para.split())
            if len(p) >= 60:
                out.append(p)
    return out


def check_risk_diff(f: corpus.Filing, rep: Report, data_dir: Path) -> None:
    """6. 风险因素年度差异：拿到同一 CIK 的上一份 10-K 就真做段落级 diff。

    第一版只比「段落序号集合」，两边序号本来就从 1 数起，几乎恒等——那种实现跑起来
    像做了事，其实什么都没比。改成按段落文本的插入/删除块比对（difflib），并只把
    新增段落的前 120 字摘出来给人核对。
    """
    peers = [m for m in corpus.discover(data_dir)
             if m["cik"] == f.cik and m["period"] != f.period]
    if not peers:
        rep.skipped.append(("风险因素年度差异",
                            f"{data_dir.name}/ 里只有 {f.cik} 的一份 10-K，无法做年度 diff"
                            f"（加 --fetch-prior 可现场补抓上年申报）"))
        return
    prev_meta = max(peers, key=lambda m: m["period"]) if peers else None
    prev = corpus.load(data_dir, prev_meta["tag"], prev_meta["period"])
    old = _risk_paragraphs(prev) if prev.period < f.period else _risk_paragraphs(f)
    new = _risk_paragraphs(f) if prev.period < f.period else _risk_paragraphs(prev)
    if not old or not new:
        rep.skipped.append(("风险因素年度差异",
                            f"两期里有一期的 Item 1A 段落抽不出来（{len(old)} 段 / {len(new)} 段），"
                            f"这项解析器认不出，不做 diff"))
        return
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(new[j1:j2])
        if tag in ("delete", "replace"):
            removed.extend(old[i1:i2])
    span = f"Item 1A {prev.period} → {f.period}"
    rep.add(Finding("风险因素年度差异",
                    f"上年 {prev.period} {len(old)} 段、本年 {f.period} {len(new)} 段；新增/改写 {len(added)} 段、"
                    f"删除/改写 {len(removed)} 段（段落级文本比对，不做语义判断）",
                    span, "逐年核对新增/改写的风险条目是否与 MD&A 的表述冲突", "info",
                    doubt="段落按空行切分，原文重排或换行变化也会被计入；条数用于定位，不做规模结论"))
    for para in added[:2]:
        rep.add(Finding("风险因素年度差异",
                        f"新增/改写的段落：「{para[:120]}…」" if len(para) > 120 else f"新增/改写的段落：「{para}」",
                        span, "确认这条新风险在本年 MD&A 里有没有对应表述", "look"))


def render(rep: Report) -> str:
    lines = [f"# {rep.entity or rep.cik} · FY10-K 复核差异表（草案，非审计意见）", ""]
    lines.append(f"- 文件：`{rep.cik}` 期间 `{rep.period}`")
    if rep.injected:
        lines.append(f"- ⚠️ 演示样本：正文里被人为改动过一处（`{rep.injected[0]}` → `{rep.injected[1]}`），"
                     "用于证明检查有效性；真实交付不会有这一行。")
    lines.append(f"- 检查项：6 项固定；本次命中 {len(rep.findings)} 条，未覆盖 {len(rep.skipped)} 项")
    lines.append("- 每条都可追到段落 ref 或 XBRL 标签；追不到的写在「未覆盖」里，不猜。")
    lines.append("")
    lines.append("| # | 检查 | 我们看到的 | 出处 | 建议动作 | 级别 |")
    lines.append("|---|---|---|---|---|---|")
    for i, x in enumerate(rep.findings, 1):
        lines.append(f"| {i} | {x.check} | {x.what} | `{x.ref}` | {x.action} | {x.severity} |")
    if rep.skipped:
        lines.append("")
        lines.append("## 未覆盖（照实说，不给结论）")
        for name, why in rep.skipped:
            lines.append(f"- **{name}**：{why}")
    lines.append("")
    lines.append("## 方法与边界")
    lines.append("- 只读公开 EDGAR 文件与 XBRL companyfacts，不接触底稿、不需要系统权限。")
    lines.append("- `mismatch` = 正文与数据口径对不上；`look` = 值得人工看一眼；`info` = 供核对的事实。")
    lines.append("- 不出审计意见、不判断重要性；四舍五入与口径差异不作为错误结论。")
    return "\n".join(lines) + "\n"


def build(cik: str, data_dir: Path, inject: tuple[str, str] | None = None) -> Report:
    f = corpus.load(data_dir, cik)
    if inject:
        # 演示用：把已知的一处数字改掉，证明这套检查真的抓得到（不是只会说「一致」）。
        # 只在临时副本上动，原始 data/ 一个字节都不改。
        old, new = inject
        html = f.path.read_text(errors="ignore")
        if old not in html:
            raise SystemExit(f"注入失败：{old!r} 不在 {f.path.name} 里")
        tmp = Path(tempfile.mkdtemp()) / f.path.name
        tmp.write_text(html.replace(old, new, 1))
        f = corpus.Filing(f.cik, tmp, f.path.with_name(f"{f.cik}_facts.json"))
    rep = Report(cik=f.cik, period=f.period)
    if f.facts_payload:
        rep.entity = f.facts_payload.get("entityName", "")
    if not f.conn:
        rep.skipped.append(("全部 XBRL 相关项", "该文件缺 facts.json"))
    else:
        check_cash_caliber(f, rep)
        check_yoy_negative_base(f, rep)
        check_segments(f, rep)
        check_text_vs_xbrl(f, rep)
        check_text_percent(f, rep)
    check_headcount_year(f, rep)
    check_risk_diff(f, rep, data_dir)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cik")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out")
    ap.add_argument("--pdf", help="同时导出一份 PDF（客户收到的是 PDF 不是 markdown）")
    ap.add_argument("--inject", nargs=2, metavar=("OLD", "NEW"),
                    help="演示用：在临时副本上改掉一处文本，验证检查能抓到")
    ap.add_argument("--fetch-prior", action="store_true",
                    help="data 目录里没有上年 10-K 时现场从 EDGAR 补抓（走 ingest 同一套清洗）")
    a = ap.parse_args(argv)
    data_dir = Path(a.data)
    if a.fetch_prior:
        peers = [m for m in corpus.discover(data_dir) if m["cik"] == a.cik]
        cur = next((m for m in peers if m["period"]), None)
        if cur is not None and len(peers) < 2:
            got = ingest.from_cik(a.cik, data_dir, prior_to=cur["period"])
            print(f"补抓上年 10-K：{got['period']}（{got['html_kb']} KB，"
                  f"accesion {got.get('accession', '?')}）", file=sys.stderr)
    rep = build(a.cik, data_dir, tuple(a.inject) if a.inject else None)
    rep.injected = tuple(a.inject) if a.inject else None
    text = render(rep)
    if a.out:
        Path(a.out).write_text(text)
        print(f"written: {a.out}")
    else:
        print(text)
    if a.pdf:
        import render_pdf
        try:
            path = render_pdf.render_pdf(text, a.pdf, title=rep.entity or a.cik)
        except render_pdf.PDFUnavailable as exc:
            print(f"PDF 没有导出：{exc}", file=sys.stderr)
            return 2
        print(f"written: {path}（{path.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
