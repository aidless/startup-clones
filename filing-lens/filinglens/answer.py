"""答案合成：先查结构化事实，再回落到原文摘录；任何答案都必须带引用，否则拒答。

这是本项目的核心契约：
- 没有引用 = 没有答案（返回 status=insufficient_evidence，而不是编一段话）。
- 数字类问题只走 XBRL，不走文本 —— 文本里的数字是别人抄错的来源。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import facts as F
from .edgar import Chunk
from . import glossary
from .index import CJK_RE, BM25Index, coverage, tokenize

MIN_COVERAGE = 0.45
# 拒答话术必须统一：客户看到两种不同的"答不了"会以为是 bug
REFUSAL = "文件里没有足够证据回答这个问题（证据不足，不作答）。"

# 数字通道的门槛：只要问题里随便出现 "revenue" 就走 XBRL 会抢答
# （"top customers concentration revenue" 被答成营收同比，明显答非所问）。
NUMERIC_CUES = ("how much", "what was", "what were", "同比增长", "同比", "多少", "金额", "revenue in")
# 定性线索必须够宽：只要问到「为什么/原因/驱动」，就不能用金额通道回答。
# 原先缺 reason/driver/decline，于是 "what was the reason for the revenue decline?"
# 被答成「revenue FY2026 为 478.83B」（status=ok conf=1.0），完全没有回答问题。
QUALITATIVE_CUES = (
    "risk", "why", "how do", "how does", "explain", "strategy", "customer", "what are",
    "reason", "reasons", "driver", "drivers", "decline", "declined", "increase driven",
    "what led", "what caused", "cause", "causes", "headwind", "tailwind", "outlook",
    "为什么", "为何", "原因", "驱动", "因素", "影响", "展望", "怎么做到",
)


def is_numeric_question(q: str) -> bool:
    low = q.lower()
    if any(c in low for c in QUALITATIVE_CUES):
        return False
    if len(tokenize(q)) <= 4:
        return True
    return any(c in low for c in NUMERIC_CUES)


@dataclass
class Citation:
    ref: str
    quote: str
    kind: str = "text"  # text | xbrl


@dataclass
class Response:
    kind: str                 # metric | excerpt | insufficient_evidence
    status: str               # ok | no_data | insufficient_evidence
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    # 出处之外必须说清楚的话（目前只有一句：摘录里的数字来自正文，不是 XBRL 口径）。
    # 存在这个字段而不是拼进 text：调用方要能分别渲染/审计，混在正文里等于没说。
    note: str = ""

    def render(self) -> str:
        head = f"[{self.status}] {self.text}"
        if self.note:
            head = f"{head}\n注：{self.note}"
        if not self.citations:
            return head
        lines = [head, "", "出处："]
        for i, c in enumerate(self.citations, 1):
            lines.append(f"  [{i}] ({c.kind}) {c.ref}")
            lines.append(f"      > {c.quote[:220]}")
        return "\n".join(lines)


YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def _is_pure_cjk(text: str) -> bool:
    """问句里有没有可用的拉丁词——没有才需要靠扩写词表撑起分母。"""
    for tok in tokenize(text):
        if not CJK_RE.search(tok) and len(tok) >= 2:
            return False
    return True


def has_quantity(sentence: str) -> bool:
    """句子里有没有「量」——年份不算。否则「2026 compared to 2025」会给任何句子加分。"""
    for raw in re.findall(r"\d[\d,.]*", sentence):
        if YEAR_RE.match(raw.strip(".,")):
            continue
        return True
    return False


def body_numbers(sentence: str) -> list[str]:
    """正文里的量（年份不算），与 has_quantity 同一口径；用来标注「这个数字不来自 XBRL」。"""
    out = []
    for raw in re.findall(r"\d[\d,.]*%?", sentence):
        if YEAR_RE.match(raw.strip(".,%")):
            continue
        out.append(raw)
    return out


# 摘录里带正文数字时的说明。文本通道可以摘原文，但不能让人以为那些数字出自 XBRL——
# 「文本通道一律不许出数字」这句话本身是假的（10-K 的定性段落里就有 48% 这种数），
# 真的契约是：数字只有 XBRL 通道能作为**答案**，正文数字必须写明来源。
BODY_NUMBER_NOTE = "摘录中的 {} 来自正文，不是 XBRL 口径"


QUANTITY_RE = re.compile(r"多少|几个|几位|几名|多少人|how many|number of|how much", re.I)

# 「有多少员工」这类问题，合格的证据只有一种句子形态：数字 + 员工。
# 用「句子里有数字且有 employees」会放过「80% 员工是技术人员」这种百分比陈述，
# 也会放过「share-based awards to employees 2,073」这种表格残渣——都在真实 10-K 上遇到过。
# 人数陈述的形态比想象的多：\"1.5 million employees\"（Amazon）、
# \"2.1 million associates\"（Walmart 不说 employees）、\"42,000 employees\"。
# 只认三位以上整数会漏掉前两种，实测 20 家里漏 4 家。
# 单位还必须含 workers/staff/headcount：Qualcomm 写的是
# \"57,000 full-time, part-time and temporary workers\"，只认 employees/people 就整句漏掉。
_HEADCOUNT_UNIT = (r"(?:employees|people|associates|team members|personnel|workers|staff"
                   r"|headcount)")
# 数字与单位之间允许的人数修饰语（\"full-time, part-time and temporary\"）
_HEADCOUNT_QUALIFIERS = (r"(?:(?:full[- ]time|part[- ]time|temporary|seasonal|permanent"
                         r"|contract|hourly|salaried|and|or|,)\s*)*")
HEADCOUNT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?(?:\s*(?:million|thousand))?)\s+"
    + _HEADCOUNT_QUALIFIERS +
    r"(?:equivalent\s+)?" + _HEADCOUNT_UNIT, re.I)

# \"65,900 and 69,700 employees, respectively\" —— 紧挨着 employees 的是**旧**数字。
RESPECTIVELY_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s+and\s+(\d[\d,]*(?:\.\d+)?)\s+(?:[a-z\-\s]{0,24})?employees", re.I)


def _is_bare_year(token: str) -> bool:
    """`2025` / `2024` 是年份；`2,024`（有千分位）是真人数。"""
    raw = token.strip()
    if "," in raw and raw.replace(",", "").isdigit() and len(raw) > 4:
        return False
    digits = raw.replace(",", "")
    return digits.isdigit() and len(digits) == 4 and 1900 <= int(digits) <= 2099


# 「X and Y employees」中间只允许出现人数修饰语；出现这些词说明 X/Y 是年份或金额。
_NOT_HEADCOUNT_GAP = re.compile(r"\b(?:as|result|of|fiscal|year|years|ended|december|january|"
                                r"february|march|april|may|june|july|august|september|october|"
                                r"november|revenue|expense|cost|respectively\b.*)", re.I)


def headcount_number(sentence: str) -> str | None:
    """从句子里取人数。双年度并列时取第一个（那是本期）。

    年份必须挡住：TI 的原句「As of December 31, 2025 and 2024, as a result of
    employees' elections…」会被 `RESPECTIVELY_RE` 读成「2025 名员工」。
    """
    for pair in RESPECTIVELY_RE.finditer(sentence):
        a, b = pair.group(1), pair.group(2)
        if _is_bare_year(a) or _is_bare_year(b):
            continue
        gap = sentence[pair.start(2) + len(b):pair.end()]
        if _NOT_HEADCOUNT_GAP.search(gap):
            continue
        return a
    m = HEADCOUNT_RE.search(sentence)
    if m and not _is_bare_year(m.group(1)):
        return m.group(0)
    return None


# 问「比例」的问题不能走金额通道：毛利率是百分数，GrossProfit 是美元。
# 表里只有几对关系是公开口径下无歧义的（分子/分母都来自 XBRL）。
RATIO_CUES_CJK = ("比例", "占比", "占收入", "占营收", "率")
# 英文线索必须按词边界匹配：concentration 里含有 ratio，
# 用子串判断会把 "top customers concentration revenue" 当成在问比例。
RATIO_CUES_EN = re.compile(r"\b(?:margin|ratio|percent|percentage)\b|%", re.I)


def wants_ratio(question: str) -> bool:
    return any(c in question for c in RATIO_CUES_CJK) or bool(RATIO_CUES_EN.search(question))


# 每对关系写成（标签, 分子, 分母, 判定函数）——判定函数吃小写问题，返回是否在问这个比例。
# 关键词只挑「毛利/净利/研发 + 比例线索」，避免把"毛利率"以外的金额问题抢过来。
RATIO_PAIRS = [
    ("毛利率", "gross_profit", "revenue",
     lambda q: ("毛利" in q or "gross margin" in q) and ("率" in q or "margin" in q)),
    ("净利率", "net_income", "revenue",
     lambda q: ("净利" in q or "net margin" in q) and ("率" in q or "margin" in q)),
    ("研发投入占收入", "r_and_d", "revenue",
     lambda q: ("研发" in q or "r&d" in q or "research and development" in q)
               and ("占" in q or "比例" in q or "率" in q)),
]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def wants_headcount_context(question: str) -> bool:
    """问的是不是「有多少员工」。

    两路判定：中文走词表概念组，英文直接认词。原先只有中文那一路，
    于是英文问 "how many employees does the company have?" 拿不到 groups=[]，
    headcount 通道与摘录通道的过滤同时失效，返回一段 AppleCare 介绍还标 status=ok。
    """
    if HEADCOUNT_QUERY_RE.search(question):
        return True
    return any("employees" in g for g in glossary.expand_groups(question))


HEADCOUNT_QUERY_RE = re.compile(
    r"\b(?:employees?|headcount|workforce|associates|personnel|workers?|staff)\b", re.I)


class Answerer:
    def __init__(self, chunks: list[Chunk], facts_conn: sqlite3.Connection | None = None):
        self.index = BM25Index().add(chunks)
        self.facts = facts_conn

    # ---- 比例通道（必须在金额通道之前）----

    def _ratio_answer(self, question: str) -> Response | None:
        if not self.facts or not wants_ratio(question):
            return None
        q = question.lower()
        for label, num, den, matches in RATIO_PAIRS:
            if matches(q):
                break
        else:
            # 提到 margin/ratio 但在问别的东西（"margin of safety" 之类）——交回文本通道，
            # 不能因为撞到一个词就替用户改问题。
            return None
        n_ser = {f.fy: f for f in F.annual_series(self.facts, num)}
        d_ser = {f.fy: f for f in F.annual_series(self.facts, den)}
        years = sorted(set(n_ser) & set(d_ser))[-3:]
        if not years:
            return Response(kind="metric", status="no_data",
                            text=f"XBRL 里缺少 {num} 或 {den} 的年度数据，算不出{label}。")
        rows = []
        for fy in years:
            n, d = n_ser[fy].val, d_ser[fy].val
            rows.append((fy, None if not d else round(n / d, 4)))
        seg = "、".join(f"FY{fy} {r:+.1%}" if r is not None else f"FY{fy} 不可算"
                       for fy, r in rows)
        last_fy, last = rows[-1]
        if last is None:
            return Response(kind="metric", status="no_data",
                            text=f"{label}：FY{last_fy} 的分母为 0，算不出来。")
        cites = [
            Citation(ref=f"XBRL:{n_ser[last_fy].tag}@FY{last_fy}",
                     quote=f"{n_ser[last_fy].tag} = {n_ser[last_fy].val:,.0f} {n_ser[last_fy].unit}",
                     kind="xbrl"),
            Citation(ref=f"XBRL:{d_ser[last_fy].tag}@FY{last_fy}",
                     quote=f"{d_ser[last_fy].tag} = {d_ser[last_fy].val:,.0f} {d_ser[last_fy].unit}",
                     kind="xbrl"),
        ]
        return Response(kind="metric", status="ok",
                        text=f"{label}：FY{last_fy} 为 {last:.2%}（近三年 {seg}）。",
                        citations=cites, confidence=0.9)

    # ---- 数字通道 ----
    def _metric_answer(self, question: str) -> Response | None:
        if not self.facts:
            return None
        if not is_numeric_question(question):
            return None
        hit = F.resolve_metric(question)
        if not hit:
            return None
        metric = hit[1]
        series = F.annual_series(self.facts, metric)
        if not series:
            return Response(kind="metric", status="no_data",
                            text=f"文件里没有 {metric} 的年度数据（XBRL 未披露）。")
        last = series[-1]
        changes = F.yoy(series)[-3:]          # 只展示近三年，30 年全列等于没回答
        seg = "、".join(
            f"FY{fy} {c:+.1%}" if c is not None else f"FY{fy} 不可比（上年为负/零）"
            for fy, c in changes
        ) or "无同比（仅一年）"
        text = (f"{metric}：FY{last.fy} 为 {F.fmt_money(last.val, last.unit)}；"
                f"近三年同比 {seg}。")
        cites = [
            Citation(ref=f"XBRL:{f.tag}@FY{f.fy}", quote=f"{f.tag} = {f.val:,.0f} {f.unit}", kind="xbrl")
            # 最新一年的引用排第一：接口只展示第一条时，不能让人以为答案出自三年前
            for f in reversed(series[-3:])
        ]
        return Response(kind="metric", status="ok", text=text, citations=cites,
                        confidence=1.0 if len(series) >= 2 else 0.7)

    # ---- 员工数：结构化的问法配结构化的找法 ----

    def _headcount_answer(self, question: str) -> Response | None:
        """「有多少员工」不走 BM25 的普通召回，直接在全文里找"N 名员工"的陈述。

        为什么单独一条路：普通召回取 top-3 段，而 10-K 里员工数常写在第 40 篇里
        一句话（"As of June 30, 2026, we employed approximately 223,000 people"），
        BM25 按查询词打分根本排不进来。实测 20 家里有 7 家的员工数就这样被漏掉，
        然后被"证据不足"拒答——拒答是诚实的，但这里本来有证据。
        """
        if not QUANTITY_RE.search(question):
            return None
        if not wants_headcount_context(question):
            return None
        pool = self.index.search("employees people workforce headcount employed", k=60)
        best = None
        for h in pool:
            for sent in _sentences(h.chunk.text):
                m = HEADCOUNT_RE.search(sent)
                if not m:
                    continue
                head = sent[:m.start()].lower()
                # 优先"我们有多少人"的陈述，其次只是顺带提到人数的句子
                strong = any(k in head for k in ("we employed", "we had", "had approximately",
                                                 "employed approximately", "had ", "headcount",
                                                 "workforce of"))
                if best is None or (strong and not best[0]):
                    best = (strong, sent, h.chunk.ref)
                if strong:
                    break
            if best and best[0]:
                break
        if best is None:
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL + "（正文未匹配到「N + 人数单位」这类句式，无法给出人数）",
                            citations=[])
        _, sent, ref = best
        return Response(kind="excerpt", status="ok", text=sent,
                        citations=[Citation(ref=ref, quote=sent, kind="text")],
                        confidence=0.8)

    # ---- 文本通道 ----
    def _excerpt_answer(self, question: str, k: int = 5) -> Response:
        # 跨语言召回：中文问句先扩成英文关键词，否则 BM25 零命中（真实 10-K 上必然发生）
        q_expanded = glossary.expand(question)
        hits = self.index.search(q_expanded, k=k)
        if not hits:
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL, citations=[])
        # 覆盖率要在 top-k 里挑「覆盖得最全的那个段落」，不能只看第一名：
        # 问「有多少员工」时第一名是讲研发费用里 headcount 成本的风险段，
        # 真正的员工数在第二名（Item 1¶51），只看 best 会把它判成证据不足。
        groups = glossary.expand_groups(question)
        scored = []
        for rank, h in enumerate(hits):
            cov_words = coverage(q_expanded, h, idf=self.index._idf)
            cov_concept = coverage(question, h, groups=groups) if groups else 0.0
            scored.append((max(cov_words, cov_concept), cov_words, cov_concept, rank, h))
        cov, cov_words, cov_concept, _, best = max(scored, key=lambda x: (x[0], -x[3]))
        if CJK_RE.search(question) and not groups:
            # 判据是「这句话里的中文，一个词表概念都没命中」，不是「覆盖率算出来是 0」。
            # 后者分母一变结论就翻：只撞上一个 ceo 也能拿 100% 覆盖（放过假答案），
            # 而员工那组五个词只出现一个就判 0（杀掉真答案，20 家里误杀 9 家）。
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL + "（问题里的中文没有命中词表里的任何概念，无法桥接到英文原文）",
                            citations=[])
        if cov < MIN_COVERAGE:
            return Response(kind="excerpt", status="insufficient_evidence",
                            text=REFUSAL + f"（最相关段落只覆盖 {cov:.0%} 的查询词）",
                            citations=[])

        q = set(tokenize(q_expanded))
        wants_number = bool(QUANTITY_RE.search(question))
        # 问员工数就必须给出"N 个员工"，不能拿一段提到 employees 的闲话充数
        wants_headcount = wants_number and wants_headcount_context(question)

        # 「多少/几个」类问题要看多段：正确答案常在别的段落（问员工数，命中段讲的是
        # 研发费用里的 headcount 成本）。所以按句子打分，跨 top-3 段落挑带数字的句子。
        scored = []
        pool = hits[:3] if wants_number else hits[:1]
        for rank, h in enumerate(pool):
            for i, sent in enumerate(_sentences(h.chunk.text)):
                overlap = len(q & set(tokenize(sent)))
                if not overlap:
                    continue
                if wants_number and not has_quantity(sent):
                    continue     # 问「多少」时，没有量的句子直接不参选
                if wants_headcount and not headcount_number(sent):
                    continue     # 员工数只认「N 个员工」的写法
                bonus = 2.0 if wants_number else 0.0
                scored.append((overlap + bonus - 0.1 * rank, rank, i, sent, h.chunk.ref))
        if not scored:
            if wants_headcount:
                # 宁可不答，也不要拿"员工里有 80% 是技术岗"当员工人数。
                return Response(kind="excerpt", status="insufficient_evidence",
                                text=REFUSAL + "（正文未匹配到「N + 人数单位」这类句式，无法给出人数）",
                                citations=[])
            quote, ref = best.chunk.text[:400], best.chunk.ref
        else:
            scored.sort(key=lambda x: (-x[0], x[1], x[2]))
            top_rank = scored[0][1]
            picked = sorted([s for s in scored if s[1] == top_rank][:2], key=lambda x: x[2])
            quote = " ".join(s[3] for s in picked)
            ref = scored[0][4]

        nums = body_numbers(quote)
        if nums and wants_number:
            # 问「多少」却没走到 XBRL：正文里的 48% 不能拿来当答案。
            # 以前这里会直接返回带数字的摘录，等于把「文本通道不出数字」的契约作废。
            return Response(
                kind="excerpt", status="insufficient_evidence",
                text=REFUSAL + f"（正文里有 {'、'.join(nums[:3])} 这类数字，但本题在问数量："
                               "数字只从 XBRL 读，正文摘录不代答）",
                citations=[])
        note = BODY_NUMBER_NOTE.format("、".join(nums[:3])) if nums else ""
        return Response(
            kind="excerpt", status="ok", text=quote,
            citations=[Citation(ref=ref, quote=quote, kind="text")],
            confidence=round(cov, 3), note=note,
        )

    def ask(self, question: str) -> Response:
        hc = self._headcount_answer(question)
        if hc is not None:
            return hc
        ratio = self._ratio_answer(question)
        if ratio is not None:
            return ratio
        metric = self._metric_answer(question)
        if metric and metric.status == "ok":
            return metric
        text = self._excerpt_answer(question)
        if metric is not None and metric.status == "no_data":
            # XBRL 明确说「这个指标没披露」时，正文摘录不得把它顶掉。
            # 否则 Amazon「研发费用是多少」会拿到一段 IPR&D 会计政策（status=ok），
            # 而英文路问同一个指标答的是 no_data——同一个事实两套结论。
            return metric
        return text if text.status == "ok" else (metric or text)
