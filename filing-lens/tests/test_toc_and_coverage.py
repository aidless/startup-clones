"""接真实 10-K 之后修的三处：目录页、跨语言召回分母、数字句筛选。

三个用例都对应 Apple FY2026 10-K 上的实测失败，不依赖网络。
"""

import re

from filinglens.answer import has_quantity
from filinglens.edgar import parse, split_sections
from filinglens.index import BM25Index, coverage
from filinglens.edgar import Chunk

TOC_DOC = """
Part I

Item 1.

Business

1

Item 1A.

Risk Factors

5

Item 1B.

Unresolved Staff Comments

20

Item 2.

Properties

20

Item 3.

Legal Proceedings

20

Item 1. Business

The Company designs and markets consumer devices and sells related services worldwide.
It operates in a highly competitive market.

Item 1A. Risk Factors

The Company's global supply chain is large and complex and a majority of its supplier
facilities are located outside the U.S., which exposes it to tariffs and trade restrictions.

Item 2. Properties

The Company owns and leases various facilities around the world.
"""


def test_toc_page_is_dropped():
    sections = split_sections(TOC_DOC)
    items = [s.item for s in sections]
    # 目录页里的 Item 1/1a/1b/2/3 全被丢掉，只剩正文那三个
    assert items == ["1", "1a", "2"], items
    assert "supplier facilities" in " ".join(sections[1].text.split())
    assert len(sections[1].text) > 100


def test_toc_does_not_eat_short_body_sections():
    """连续短正文不能被当成目录页误删（Item 4/5/6 常常只有一句话）。"""
    doc = """
Item 4. Mine Safety Disclosures

Not applicable.

Item 5. Market for Registrant's Common Equity

The Company's common stock trades on Nasdaq.

Item 6. [Reserved]

Reserved.
"""
    items = [s.item for s in split_sections(doc)]
    assert items == ["4", "5", "6"], items


def test_coverage_ignores_chinese_characters():
    """中文提问在英文语料里：分母只算拉丁词，否则永远判证据不足。"""
    chunk = Chunk(doc="F", item="1", section="Business", para=1,
                  text="The Company's global supply chain is large and complex.")
    idx = BM25Index().add([chunk])
    hit = idx.search("supply chain")[0]
    # 中文 6 个字 + 英文 2 个词：若把中文字算进分母，覆盖率上限只有 2/8
    assert coverage("供应链主要依赖哪些地区 supply chain", hit, idf=idx._idf) == 1.0
    assert coverage("供应链主要依赖哪些地区 supply chain", hit) == 1.0


def test_idf_weighting_rejects_ubiquitous_term():
    """在全是 "apple" 的语料里靠 apple 命中不算答上了。"""
    chunks = [Chunk(doc="F", item="1", section="Business", para=i,
                    text="Apple designs products. Apple sells services.") for i in range(10)]
    idx = BM25Index().add(chunks)
    hit = idx.search("apple ceo")[0]
    assert coverage("apple ceo", hit, idf=idx._idf) < 0.45


def test_has_quantity_excludes_years():
    assert not has_quantity("Revenue grew in 2026 compared to 2025.")
    assert has_quantity("The Company had approximately 167,000 full-time equivalent employees.")
    assert has_quantity("Gross margin was 46.2%.")


def test_parse_marks_no_sections_when_input_is_plain_text():
    sections, chunks, tables = parse("<html><body><p>hello world</p></body></html>", doc="X")
    assert sections and sections[0].item == "0"
    assert tables == []
