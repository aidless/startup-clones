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
    from bs4 import BeautifulSoup

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


def split_sections(text: str) -> list[Section]:
    matches = list(ITEM_RE.finditer(text))
    sections: list[Section] = []
    for i, m in enumerate(matches):
        item = m.group(1).lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if not body:
            continue
        title = ITEM_NAMES.get(item, m.group(2).strip()[:80] or f"Item {item}")
        sections.append(Section(item=item, title=title, text=body))
    if not sections:
        sections.append(Section(item="0", title="Full Text", text=text.strip()))
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
