"""EDGAR 抓取与解析。

两个硬约束：
1. 表格不进向量库 —— 财报表格是结构化的，进文本索引必然检索错，必须走 XBRL/表格通道。
2. 每个段落都要可定位（section + para 序号 + 字符偏移），否则答案无法引用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ITEM_RE = re.compile(
    r"^\s*item\s+(\d{1,2}[a-c]?)\s*[.:\-—]?\s*(.{0,120})$", re.IGNORECASE | re.MULTILINE
)

ITEM_NAMES = {
    "1": "Business",
    "1a": "Risk Factors",
    "1b": "Unresolved Staff Comments",
    "2": "Properties",
    "3": "Legal Proceedings",
    "7": "MD&A",
    "7a": "Quantitative and Qualitative Disclosures",
    "8": "Financial Statements",
    "9": "Controls and Procedures",
}


@dataclass
class Section:
    item: str
    title: str
    text: str


@dataclass
class Chunk:
    doc: str
    item: str
    section: str
    para: int
    text: str
    start: int = 0  # 在 section 全文中的字符偏移

    @property
    def ref(self) -> str:
        return f"{self.doc}#Item {self.item}¶{self.para}"


@dataclass
class Table:
    doc: str
    item: str
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def html_to_text(html: str) -> str:
    import warnings

    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    # SEC 的 .htm 常常是 XHTML，用 lxml 的 HTML 解析器足够，屏蔽这条噪音警告
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # 保留块级换行
    for tag in soup.find_all(["p", "div", "br", "tr", "h1", "h2", "h3", "li"]):
        tag.insert_after("\n")
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n"))


TOC_PAGE_RE = re.compile(r"[ivxlc\d]{1,4}", re.I)


def _is_toc_gap(gap: str) -> bool:
    """目录页的判据不在「间距短」，而在「两个 Item 之间只剩页码」。

    只用间距会误伤连续短正文（Item 4. Mine Safety Disclosures: Not applicable.），
    而真实 10-K 的目录页每条后面恰好是一行页码。
    """
    g = " ".join(gap.split())
    return bool(g) and len(g) <= 40 and bool(TOC_PAGE_RE.fullmatch(g))


def _strip_toc(text: str, matches: list) -> list:
    """丢掉目录页（Table of Contents）里的 Item 行。

    真实 10-K 开头一定有一页目录，把所有 Item 列成「Item 1. Business / 1」。
    不处理它，解析结果就是一堆正文只有 1~2 个字符的 Section（Apple FY2026 实测 46 段）。
    判据：连续两条以上「条目之间只剩页码」的间隔 = 目录页，整条链丢掉。
    """
    if len(matches) < 2:
        return matches
    gaps = [" ".join(text[matches[k].end():matches[k + 1].start()].split())
            for k in range(len(matches) - 1)]
    toc_like = [_is_toc_gap(g) for g in gaps]
    drop = [False] * len(matches)
    if sum(toc_like) >= 2:          # 单独一条「后面正好是个数字」不算目录页
        for k, like in enumerate(toc_like):
            if like:
                drop[k] = True
    return [m for m, d in zip(matches, drop) if not d]


MIN_SEGMENT_CHARS = 400     # 低于这个长度的同 Item 片段当目录/交叉引用碎屑
MIN_BODY_RATIO = 0.15       # 结构化抽取至少保留 15% 正文，否则判定结构识别失败


def split_sections(text: str) -> list[Section]:
    matches = _strip_toc(text, list(ITEM_RE.finditer(text)))
    found: list[tuple[int, Section]] = []
    for i, m in enumerate(matches):
        item = m.group(1).lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if not body:
            continue
        title = ITEM_NAMES.get(item, m.group(2).strip()[:80] or f"Item {item}")
        found.append((m.start(), Section(item=item, title=title, text=body)))

    # 同一个 Item 可能命中多次，两种成因：
    #   ① 目录页 / 交叉引用（"Item 4. Mine Safety ... 21"）——碎片，该丢；
    #   ② 每页页眉重复印着 "Item 1"（Microsoft 的 10-K 就是这样）——正文被切成
    #      每段只有几千字，若"只留最长的那份"，正文会丢掉 88%（实测 393k 字符剩 45k）。
    # 所以按"够长的都留、按文档顺序拼起来"处理：碎屑（< MIN_SEGMENT）丢掉，
    # 实质段落（>= MIN_SEGMENT）合并。代价是交叉引用带进来的那点内容会被重复归属。
    merged: dict[str, list[Section]] = {}
    for pos, sec in found:
        merged.setdefault(sec.item, []).append(sec)

    sections: list[Section] = []
    for item, segs in merged.items():
        substantive = [s for s in segs if len(s.text) >= MIN_SEGMENT_CHARS]
        keep = substantive or [max(segs, key=lambda s: len(s.text))]
        sections.append(Section(item=item, title=keep[0].title,
                                text="\n\n".join(s.text for s in keep)))

    # 结构识别失败时不能返回碎片：有的 10-K 正文根本不用 "Item N." 做标题
    # （Intel 就是：只有目录页写 Item，正文是 "Risk Factors" 这种裸标题）。
    # 这时整篇当一段文本，检索照常工作——只是失去 Item 归属。
    body_chars = sum(len(s.text) for s in sections)
    if not sections or body_chars < MIN_BODY_RATIO * len(text):
        return [Section(item="0", title="Full Text", text=text.strip())]
    return sections


def chunk_sections(doc: str, sections: list[Section], min_len: int = 80) -> list[Chunk]:
    chunks: list[Chunk] = []
    for sec in sections:
        offset = 0
        para_no = 0
        for raw in re.split(r"\n\s*\n", sec.text):
            para_no += 1
            body = " ".join(raw.split())
            if len(body) >= min_len:
                chunks.append(Chunk(doc=doc, item=sec.item, section=sec.title,
                                    para=para_no, text=body, start=offset))
            offset += len(raw) + 2
    return chunks


def parse(html: str, doc: str = "FILING") -> tuple[list[Section], list[Chunk], list[Table]]:
    text = html_to_text(html)
    sections = split_sections(text)
    chunks = chunk_sections(doc, sections)
    tables = extract_tables(html, doc, sections)
    return sections, chunks, tables


def extract_tables(html: str, doc: str, sections: list[Section]) -> list[Table]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: list[Table] = []
    for t in soup.find_all("table"):
        rows = []
        for tr in t.find_all("tr"):
            cells = [" ".join(td.get_text(" ").split()) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2:
            # 归属到最可能的小节：取表格前置文本里最后一个 Item
            prev = t.find_previous(string=ITEM_RE)
            item = "0"
            if prev:
                m = ITEM_RE.search(prev)
                if m:
                    item = m.group(1).lower()
            out.append(Table(doc=doc, item=item, header=rows[0], rows=rows[1:]))
    return out


def fetch_filing(url: str, user_agent: str) -> str:
    """真实抓取。SEC 要求带 User-Agent（含邮箱），否则 403。"""
    import httpx

    r = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    return r.text


def companyfacts_url(cik: str) -> str:
    cik = str(cik).lstrip("0").zfill(10)
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
