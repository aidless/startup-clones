"""监管往来函件（SEC comment letter / 公司回复）的结构化与线程重建。

这批语料和普通邮件不一样，三条硬特征决定了产品该怎么做：

1. **每封信都在回答上一封的某一天**（"the comments contained in the letter dated March 6, 2024"），
   所以线程不能靠 subject 猜，得靠信里自述的被回复日期。
2. **每条意见都有编号**，回复必须逐条对应；漏一条就是漏答。
3. **有保密请求**（FOIA Confidential Treatment / Rule 83），这类内容不能进普通审批流，
   必须单独走法务。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

# 月份表必须用 (?:...) 包住：交替的优先级最低，漏了它 "(January|February\s+\d{1,2})"
# 会被解读成「January」或「February + 数字」，group(1) 就只剩月份名（实测踩过）。
_MONTH_ALT = "(?:" + "|".join(MONTHS) + ")"
DATE_RE = re.compile(r"\b(" + _MONTH_ALT + r")\s+(\d{1,2}),\s+(\d{4})\b")
RE_RUN_RE = re.compile(r"^Re:\s*$", re.I)
FORM_RE = re.compile(r"Form\s+(\d{1,2}-[A-Z]{1,3})\s+for the fiscal year ended\s+("
                     + _MONTH_ALT + r"\s+\d{1,2},\s+\d{4})", re.I)
FILE_NO_RE = re.compile(r"File No\.?\s*([0-9]{1,3}-[0-9]{1,6})")
DATED_RE = re.compile(r"dated\s+(" + _MONTH_ALT + r"\s+\d{1,2},\s+\d{4})")
NUMBERED_RE = re.compile(r"^\s*(\d{1,2})\.\s+(\S.*)$")
CONFIDENTIAL_MARKERS = ("FOIA CONFIDENTIAL TREATMENT", "Rule 83", "17 C.F.R. § 200.83")
DEAR_RE = re.compile(r"^Dear\b", re.I)
# 回复函里逐条回应的常见引导语
REPLY_LEAD_RE = re.compile(
    r"(Response:|We (?:acknowledge|note|respectfully submit|supplement)|"
    r"The (?:Company|Staff) (?:respectfully )?(?:acknowledges|notes|submits|refers))", re.I)


def parse_date(raw: str) -> tuple[int, int, int]:
    m = re.match(r"(" + _MONTH_ALT + r")\s+(\d{1,2}),\s+(\d{4})", raw.strip())
    if not m:
        raise ValueError(f"无法解析日期: {raw!r}")
    return int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))


def norm_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.replace("\r", "").splitlines()]
    return [ln for ln in lines if ln]


@dataclass
class Letter:
    doc_id: str
    date: tuple[int, int, int]
    form: str | None = None
    fiscal_year_end: str | None = None
    file_no: str | None = None
    responds_to: tuple[int, int, int] | None = None
    responds_to_raw: str | None = None
    confidential: bool = False
    addressed_to: str | None = None
    numbered: dict[int, str] = field(default_factory=dict)
    reply_items: list[str] = field(default_factory=list)
    body_chars: int = 0

    @property
    def thread_key(self) -> str:
        return f"{self.form or 'UNKNOWN'}|{self.file_no or 'NO-FILE'}"

    def render(self) -> str:
        d = "%04d-%02d-%02d" % self.date
        bits = [f"{d}  {self.form or '?'}  file={self.file_no or '-'}  段落={self.body_chars}"]
        if self.responds_to:
            bits.append("  回应 " + self.responds_to_raw)
        if self.numbered:
            bits.append(f"  编号条目 {len(self.numbered)} 条")
        if self.reply_items:
            bits.append(f"  逐条回应 {len(self.reply_items)} 处")
        if self.confidential:
            bits.append("  [保密请求 → 法务]")
        return "".join(bits)


def _response_target(flat: str) -> re.Match | None:
    """找「这封信在回复哪一天」的那封信。

    坑：Re: 块里也有日期，但那是背景（"Response dated March 20, 2024"）。
    真正的被回复日期出现在正文里，前面跟着 letter / comments。
    """
    fallback = None
    for m in DATED_RE.finditer(flat):
        if fallback is None:
            fallback = m
        prefix = flat[max(0, m.start() - 160):m.start()].lower()
        # 「Response dated X」是背景（上一轮自己那封信），不是被回复对象。
        # 注意 prefix 里只到 "dated" 之前，所以要看结尾是不是 Response。
        if re.search(r"response\s*$", prefix):
            continue
        if "letter" in prefix or "comment" in prefix:
            return m
    return fallback


def parse_letter(text: str, doc_id: str = "DOC") -> Letter:
    lines = norm_lines(text)
    # 第一段日期就是落款日期（信头），不要取正文里提到的日期
    date = None
    for ln in lines[:40]:
        m = DATE_RE.search(ln)
        if m:
            date = parse_date(m.group(0))
            break
    if date is None:
        raise ValueError("找不到落款日期")

    joined = "\n".join(lines)
    # 真实函件在 72 列处硬换行，"April\n2, 2024" 会被拆成两行，日期正则就抓不到了
    flat = re.sub(r"\s+", " ", joined)
    form_m = FORM_RE.search(flat)
    file_m = FILE_NO_RE.search(flat)
    dated_m = _response_target(flat)

    letter = Letter(
        doc_id=doc_id, date=date,
        form=form_m.group(1) if form_m else None,
        fiscal_year_end=form_m.group(2) if form_m else None,
        file_no=file_m.group(1) if file_m else None,
        responds_to_raw=re.sub(r"\s+", " ", dated_m.group(1)) if dated_m else None,
        responds_to=parse_date(dated_m.group(1)) if dated_m else None,
        confidential=any(m in joined for m in CONFIDENTIAL_MARKERS),
        body_chars=len(joined),
    )

    # Re: 块里的内容（Form / 财年 / File No / Response dated）
    for i, ln in enumerate(lines):
        if DEAR_RE.match(ln):
            letter.addressed_to = ln
            break

    # 编号条目：只在「Dear」之后找，避免把地址里的编号当意见
    start = next((i for i, ln in enumerate(lines) if DEAR_RE.match(ln)), 0)
    for ln in lines[start:]:
        m = NUMBERED_RE.match(ln)
        if m and len(m.group(2)) > 25:
            letter.numbered[int(m.group(1))] = m.group(2)[:300]

    # 逐条回应：以引导语开头的段落，数量要和来函条目数一致才算答全
    letter.reply_items = [ln[:200] for ln in lines[start:] if REPLY_LEAD_RE.match(ln)]
    return letter


@dataclass
class Gap:
    thread_key: str
    doc_id: str
    reason: str


def build_threads(letters: list[Letter]) -> tuple[list[list[Letter]], list[Gap]]:
    """按 (form, file_no) 线程化，用「自述被回复日期」串链，并报出断链。"""
    groups: dict[str, list[Letter]] = {}
    for l in letters:
        groups.setdefault(l.thread_key, []).append(l)
    threads, gaps = [], []
    for key, group in groups.items():
        group.sort(key=lambda l: l.date)
        threads.append(group)
        by_date = {l.date: l for l in group}
        for prev, cur in zip(group, group[1:]):
            if cur.responds_to is None:
                gaps.append(Gap(key, cur.doc_id, "没有自述被回复日期，无法确认是否接续"))
                continue
            target = by_date.get(cur.responds_to)
            if target is None:
                # 这是常态而不是错误：SEC 的员工意见函通常不在同一 CIK 的 CORRESP 里
                gaps.append(Gap(key, cur.doc_id,
                                f"被回复的信（{cur.responds_to_raw}）不在语料中，需另行取得"))
            elif target is not prev:
                gaps.append(Gap(key, cur.doc_id,
                                f"回应 {cur.responds_to_raw}，但时间上更近的上一封是 "
                                f"%04d-%02d-%02d" % prev.date))
    threads.sort(key=lambda t: t[0].date)
    return threads, gaps


def escalate(letter: Letter) -> list[str]:
    """这封信该进哪条审批流。监管 + 保密 = 不能走普通出口审批。"""
    tags = ["regulator"]
    if letter.confidential:
        tags.append("confidential")
    if letter.numbered:
        tags.append("numbered-requests")
    return tags


def approval_route(letter: Letter) -> str:
    """保密函件不能走普通出口审批：普通审批人会看到正文，而这正是 Rule 83 要挡住的。

    返回 "legal" 表示必须由法务审，且正文不进普通审批队列。
    """
    return "legal" if letter.confidential else "compliance"
