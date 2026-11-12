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
