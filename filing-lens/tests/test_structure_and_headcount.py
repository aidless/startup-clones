"""20 家公司逼出来的两处结构问题 + 员工数路径。

这三组断言的共同点是：它们都不是我设计时想到的场景，是基准跑出来才发现的。
所以每条都写着「哪家公司、什么症状」，改了这条断言的人能看见自己在改什么。
"""

from __future__ import annotations

import sqlite3

from filinglens import answer, edgar, facts, index
from filinglens.answer import headcount_number


# ---------------------------------------------------------------- 结构：页眉把正文切碎

def test_repeated_running_headers_are_merged_not_dropped():
    """Microsoft 的 10-K 每页页眉都印着 "Item 1"，正文被切成 4k 级别的碎段。

    旧实现「同 Item 只留最长那份」→ 393k 字符只剩 45k（丢 88%）。
    正确做法：够长的同 Item 片段全留并按文档顺序合并。
    """
    body_a = "Our business is a technology company. " * 200
    body_b = "The Microsoft Cloud provides integration across the stack. " * 200
    text = (f"Item 1. Business\n{body_a}\n"
            f"Item 1\n{body_b}\n"
            f"Item 1A. Risk Factors\n{'Risk text. ' * 300}\n")
    sections = edgar.split_sections(text)
    item1 = next(s for s in sections if s.item == "1")
    assert "technology company" in item1.text
    assert "Microsoft Cloud" in item1.text, "页眉重复出现时，第二段正文必须留在同一个 Item 里"


def test_good_structure_keeps_item_attribution():
    """回退不能变成常态：结构没问题时必须保留 Item 归属（否则引用都指向 "Item 0"）。"""
    body = "Our supply chain relies on contract manufacturers. " * 200
    text = f"Item 1. Business\n{body}\nItem 1A. Risk Factors\n{'Risk text. ' * 400}\n"
    sections = edgar.split_sections(text)
    assert {s.item for s in sections} == {"1", "1a"}


def test_structure_failure_falls_back_to_full_text():
    """Intel 的 10-K 正文根本不用 "Item N." 做标题，只有目录页写 Item。

    旧实现返回一堆目录碎屑，检索全空（908 段变 3 段）。
    正确做法：结构化抽取保留的正文不足 15% 时，整篇当一段文本。
    """
    # 真实成因：Intel 的 "Item N" 只出现在文末的索引页里（23 处全挤在最后 2k 字符），
    # 前面 571k 字符的正文一个都没有——所以按 Item 切出来的总长度不到全文的 1%。
    body = ("We face intense competition in every market we serve, and that competition "
            "could harm our results of operations.\n\n") * 300
    tail_index = "Item 1. Business Pages 3\nItem 1A. Risk Factors Pages 37\nItem 2. Properties Pages 11\n"
    sections = edgar.split_sections(body + tail_index)
    assert len(sections) == 1 and sections[0].item == "0"
    assert len(sections[0].text) > 10_000, "回退后必须保住正文，不能只剩目录"
    chunks = edgar.chunk_sections("DOC", sections)
    assert len(chunks) > 20


# ---------------------------------------------------------------- 员工数的写法

def test_headcount_patterns_across_real_phrasings():
    assert headcount_number("we employed approximately 1,576,000 full-time and part-time employees.") \
        == "1,576,000 full-time and part-time employees"          # Amazon
    assert headcount_number("2.1 million associates") == "2.1 million associates"   # Walmart
    assert headcount_number("approximately 167,000 full-time equivalent employees.") \
        .startswith("167,000")                                    # Apple
    assert headcount_number("more than 80 percent have technical roles") is None   # NVDA 的干扰句


def test_two_year_sentence_takes_the_current_year():
    """Coca-Cola：\"65,900 and 69,700 employees, respectively\"——贴着 employees 的是旧数字。"""
    assert headcount_number("had approximately 65,900 and 69,700 employees, respectively") == "65,900"


# ---------------------------------------------------------------- 员工数必须走全文

def _answerer(chunks_text: list[str], conn: sqlite3.Connection | None = None):
    chunks = [edgar.Chunk(doc="D", item="1", section="Business", para=i, text=t, start=0)
              for i, t in enumerate(chunks_text)]
    return answer.Answerer(chunks, conn)


def test_headcount_found_even_when_bm25_ranks_it_last():
    """员工数常写在第 40 篇里一句话，BM25 按查询词打分排不进来——但它就是答案。"""
    noise = ["Our research and development expenses include headcount costs for engineers. " * 3] * 6
    target = "As of June 30, 2026, we employed approximately 223,000 people on a full-time basis."
    a = _answerer(noise + [target])
    r = a.ask("有多少员工？")
    assert r.status == "ok", r.text
    assert "223,000" in r.text
    assert r.citations and r.citations[0].ref == "D#Item 1¶6"


def test_headcount_without_a_number_refuses():
    """文件里只会说「多数员工是技术岗」时，不能把这句话当人数。"""
    a = _answerer(["More than 80 percent of our workforce have technical roles. " * 3])
    r = a.ask("有多少员工？")
    assert r.status == "insufficient_evidence"
    assert r.citations == []


# ---------------------------------------------------------------- 中文拒答判据

def test_chinese_without_any_glossary_concept_refuses():
    """「CEO 的生日是哪天」只撞上 ceo 一个词——分母缩到一个词就能拿 100% 覆盖。"""
    a = _answerer(["Our CEO, Satya Nadella, was born in Hyderabad. " * 3])
    assert a.ask("CEO 的生日是哪天？").status == "insufficient_evidence"


def test_chinese_question_with_mapped_concept_is_answered():
    a = _answerer(["Tariffs increased our cost of sales in the current fiscal year. " * 3])
    r = a.ask("关税对成本有什么影响？")
    assert r.status == "ok" and r.citations


def test_metric_citation_points_at_the_year_in_the_answer():
    """接口通常只展示第一条引用——排在第一位的那年必须是答案里写的那年。"""
    conn = sqlite3.connect(":memory:")
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2023-01-01", "end": "2023-12-31",
         "filed": "2024-02-01", "val": 100},
        {"form": "10-K", "fp": "FY", "fy": 2025, "start": "2024-01-01", "end": "2024-12-31",
         "filed": "2025-02-01", "val": 130},
    ]}}}}}
    facts.load_companyfacts(payload, db_path=":memory:")
    a = answer.Answerer([], facts.load_companyfacts(payload, db_path=":memory:"))
    r = a.ask("营收多少")
    assert "FY2025" in r.text
    assert r.citations[0].ref == "XBRL:Revenues@FY2025", r.citations[0].ref
