"""核心契约测试：没有引用就没有答案。"""
import pytest

from filinglens import edgar, facts as F, fixtures
from filinglens.answer import Answerer


@pytest.fixture(scope="module")
def ans():
    _, chunks, _ = edgar.parse(fixtures.FAKE_10K_HTML, doc="ACME")
    conn = F.load_companyfacts(fixtures.FAKE_FACTS, ":memory:")
    return Answerer(chunks, conn)


def test_metric_question_uses_xbrl_not_text(ans):
    r = ans.ask("revenue")
    assert r.kind == "metric" and r.status == "ok"
    assert "175.0M" in r.text
    assert "+34.6%" in r.text
    assert all(c.kind == "xbrl" for c in r.citations)


def test_net_income_decline_then_growth(ans):
    r = ans.ask("net income")
    assert "15.0M" in r.text
    assert "-20.0%" in r.text and "+87.5%" in r.text


def test_text_question_cites_item(ans):
    r = ans.ask("lidar supplier concentration risk")
    assert r.status == "ok" and r.kind == "excerpt"
    assert r.citations and "#Item 1a" in r.citations[0].ref
    assert "lidar" in r.citations[0].quote.lower()


def test_off_topic_question_refuses(ans):
    r = ans.ask("cryptocurrency mining plan in Argentina")
    assert r.status == "insufficient_evidence"
    assert r.citations == []
    assert "证据不足" in r.text


def test_no_ok_without_citation(ans):
    """不变式：任何 ok 的答案都必须至少有一条引用。"""
    for q in ["revenue", "risk factors", "gross margin", "研发", "board of directors"]:
        r = ans.ask(q)
        if r.status == "ok":
            assert r.citations, f"missing citation for {q!r}"


def test_render_contains_status_and_source(ans):
    out = ans.ask("revenue").render()
    assert out.startswith("[ok]")
    assert "出处：" in out and "XBRL:" in out


def test_metric_word_in_qualitative_question_does_not_hijack(ans):
    """回归：问题里出现 revenue 不代表在问金额。"""
    r = ans.ask("top customers concentration revenue")
    assert r.kind == "excerpt"
    assert r.citations and "#Item 1a" in r.citations[0].ref


def test_concept_coverage_rescues_pure_chinese_question():
    """纯中文提问靠词表概念命中，不该被同义词撑大的分母压成「证据不足」。

    供应链 → supply chain suppliers manufacturing 四个词，夹具段落只用了其中两个；
    词级覆盖 0.434 < 0.45 会拒答，概念级覆盖能救回来。
    """
    from filinglens import edgar, fixtures, glossary, index

    _, chunks, _ = edgar.parse(fixtures.FAKE_10K_HTML, doc="X")
    idx = index.BM25Index().add(chunks)
    q = "供应链集中在哪些地区？"
    best = idx.search(glossary.expand(q), k=1)[0]
    words = index.coverage(glossary.expand(q), best, idf=idx._idf)
    concept = index.coverage(q, best, groups=glossary.expand_groups(q))
    assert words < 0.45
    assert concept >= 0.45


def test_concept_coverage_does_not_apply_without_glossary_hit():
    """「生日」不在词表里 → 没有概念可救，必须保持拒答。

    这正是「CEO 生日」曾被 Apple Arcade 段落骗过去的那个洞。
    """
    from filinglens import glossary

    assert glossary.expand_groups("CEO 的生日是哪天") == []


def test_single_latin_token_cannot_carry_an_unbridgeable_chinese_question():
    """「CEO 的生日是哪天」曾经被判 ok，覆盖率 100%。

    原因：中文单字不进分母，分母只剩 ceo 一个词，任何含 CEO 的段落都拿满分。
    契约：中文提问必须有词表概念被命中，否则拒答。
    """
    from filinglens import answer, edgar

    html = (
        "<html><body>"
        "<p>Item 1. Business</p>"
        "<p>The Company's CEO is its chief operating decision maker. "
        "Our CEO has served since 2011 and reports to the board of directors. "
        "The board meets quarterly to review performance and capital allocation.</p>"
        "<p>Item 7. MD&amp;A</p>"
        "<p>Revenue grew in fiscal 2025 on higher unit volume and improved pricing.</p>"
        "</body></html>"
    )
    _, chunks, _ = edgar.parse(html, doc="T")
    a = answer.Answerer(chunks, None)

    bad = a.ask("CEO 的生日是哪天")
    assert bad.status == "insufficient_evidence"
    assert bad.citations == []
    assert "词表" in bad.text

    good = a.ask("董事会有多少人")
    assert good.status == "ok" and good.citations
