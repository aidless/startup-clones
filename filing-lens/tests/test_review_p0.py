"""审查报告 P0 三条的复现测试（2026-11-12 审查）。

这三条的共同点：都给出一份「看起来完全正确」的答案——
status=ok、confidence=1.0、引用是真实的 XBRL 标签与真实的数字，
而科目 / 语义完全错了。用户没有第二个信息源能发现。

每个测试对应报告里的一条，先红后绿（AGENTS.md 第 27 条）。
"""
from __future__ import annotations

from filinglens import facts as F
from filinglens.answer import Answerer, is_numeric_question
from filinglens.edgar import parse

# 同一份 facts 里既有现金余额、又有经营活动现金流——这正是真实 companyfacts 的样子
CFO_PAYLOAD = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {"USD": [
                    {"end": "2026-09-26", "val": 36_300_000_000, "fy": 2026, "fp": "FY",
                     "form": "10-K", "filed": "2026-10-30"},
                ]},
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [
                    {"end": "2026-09-26", "val": 145_100_000_000, "fy": 2026, "fp": "FY",
                     "form": "10-K", "filed": "2026-10-30"},
                ]},
            },
            "Revenues": {
                "units": {"USD": [
                    {"end": "2026-09-26", "val": 478_830_000_000, "fy": 2026, "fp": "FY",
                     "form": "10-K", "filed": "2026-10-30"},
                ]},
            },
        }
    },
}

HTML = """
<html><body>
<p>Item 1. Business</p>
<p>As of September 26, 2026, the Company had approximately 167,000 full-time equivalent
employees, including 76,000 in the United States.</p>
<p>Item 1A. Risk Factors</p>
<p>Supply chain concentration is our most significant operational risk. The Company relies on
a small number of suppliers and contract manufacturers.</p>
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>
<p>Total revenue increased 15% to $478.83 billion in fiscal 2026, driven by services growth.</p>
<p>Item 8. Financial Statements and Supplementary Data</p>
<p>Cash and cash equivalents were $36.30 billion at September 26, 2026.</p>
</body></html>
"""


def _answerer() -> Answerer:
    sections, chunks, _tables = parse(HTML, doc="0000320193")
    conn = F.load_companyfacts(CFO_PAYLOAD)
    return Answerer(chunks, conn)


# ---- P0-1：经营活动现金流被答成现金余额 ----

def test_operating_cash_flow_uses_cfo_tag_not_cash_balance():
    r = _answerer().ask("What was cash flow from operations in FY2026?")
    assert r.status == "ok", r.render()
    assert "145.1" in r.text, f"必须是经营活动现金流 145.1B，实际：{r.text}"
    assert "NetCashProvidedByUsedInOperatingActivities" in " ".join(c.ref for c in r.citations)


def test_operating_cash_flow_chinese_question():
    r = _answerer().ask("经营活动现金流是多少？")
    assert r.status == "ok", r.render()
    assert "145.1" in r.text, r.text


def test_cash_balance_question_still_answers_cash():
    # 正对照：问「现金余额」时不能被改成答现金流（防止修过头）
    r = _answerer().ask("How much cash and cash equivalents did the company hold in FY2026?")
    assert r.status == "ok", r.render()
    assert "36.3" in r.text, r.text


# ---- P0-2：定性问题被数字通道抢答 ----

def test_reason_question_is_not_routed_to_metric():
    assert is_numeric_question("what was the reason for the revenue decline?") is False
    r = _answerer().ask("what was the reason for the revenue decline?")
    assert r.kind != "metric", f"定性问题不该走金额通道：{r.text}"


def test_growth_drivers_question_is_not_routed_to_metric():
    assert is_numeric_question("revenue growth drivers") is False
    r = _answerer().ask("revenue growth drivers")
    assert r.kind != "metric", f"定性问题不该走金额通道：{r.text}"


def test_numeric_question_still_numeric():
    # 正对照：真正的数字问题必须继续走 XBRL
    assert is_numeric_question("what was revenue in FY2026?") is True
    assert is_numeric_question("营收是多少？") is True


# ---- P0-3：英文问员工数落不到 headcount 通道 ----

def test_english_headcount_question_returns_a_number():
    r = _answerer().ask("how many employees does the company have?")
    assert r.status == "ok", r.render()
    assert "167,000" in r.text, f"应给出 167,000 名员工，实际：{r.text}"


def test_chinese_headcount_question_still_works():
    # 正对照：中文路径原本就对，修英文不能把它弄坏
    r = _answerer().ask("公司有多少员工？")
    assert r.status == "ok", r.render()
    assert "167,000" in r.text, r.text
