"""监管往来函件解析：三条规则都是在真实 SEC CORRESP 上被逼出来的。"""

import pytest

from agentinbox.corresp import approval_route, build_threads, escalate, parse_letter

REPLY = """CORRESP
Apple Inc.
One Apple Park Way
Cupertino, CA 95014

April 29, 2024

BY EDGAR

To:
U.S. Securities and Exchange Commission
Division of Corporation Finance

Re:
Apple Inc.
Form 10-K for the fiscal year ended September 30, 2023
Response dated March 20, 2024
File No. 001-36743

Dear Mses. Kindelan and Collins,

Apple Inc. (the "Company") provides the following response to the comments contained in
the letter (the "Comment Letter") of the staff of the Division of Corporation Finance,
dated April 2, 2024, relating to the above-referenced filing.

FOIA CONFIDENTIAL TREATMENT REQUESTED PURSUANT TO RULE 83.

1. We acknowledge the Staff's comment regarding segment reporting and confirm that the
   Company will revise its disclosure in future filings to describe the chief operating
   decision maker's review process.

2. We respectfully submit that the Company's presentation is consistent with the guidance
   and will enhance its disclosure in the Form 10-K for the fiscal year ending 2024.
"""

STAFF = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Division of Corporation Finance
Office of Technology

April 2, 2024

Apple Inc.
One Apple Park Way
Cupertino, CA 95014

Re:
Apple Inc.
Form 10-K for the fiscal year ended September 30, 2023
File No. 001-36743

Dear Mses. Kindelan and Collins:

1. We note the Company's disclosure regarding segment reporting. Please tell us how the
   chief operating decision maker evaluates performance and allocates resources.

2. We note your response to prior comment 1. Please provide additional detail regarding
   the timing of revenue recognition for services.
"""


def test_response_target_skips_background_response_date():
    """Re: 块里的 "Response dated March 20" 是背景，被回复的是正文里的 April 2。"""
    letter = parse_letter(REPLY, doc_id="A")
    assert letter.responds_to_raw == "April 2, 2024"
    assert letter.responds_to == (2024, 4, 2)
    assert letter.date == (2024, 4, 29)


def test_numbered_and_confidential_flags():
    letter = parse_letter(REPLY, doc_id="A")
    assert letter.confidential is True
    assert sorted(letter.numbered) == [1, 2]
    assert letter.form == "10-K"
    assert letter.file_no == "001-36743"
    assert escalate(letter) == ["regulator", "confidential", "numbered-requests"]


def test_staff_letter_has_no_confidential_flag():
    letter = parse_letter(STAFF, doc_id="S")
    assert letter.confidential is False
    assert letter.date == (2024, 4, 2)
    assert escalate(letter) == ["regulator", "numbered-requests"]


def test_thread_reports_missing_predecessor():
    """SEC 员工意见函通常不在公司的 CORRESP 里 —— 这不是解析错误，是要报出来的缺口。"""
    letters = [parse_letter(REPLY, doc_id="A")]
    threads, gaps = build_threads(letters)
    assert len(threads) == 1 and len(threads[0]) == 1
    assert len(gaps) == 0        # 单封无法判断接续，不该瞎报

    letters = [parse_letter(STAFF, doc_id="S"), parse_letter(REPLY, doc_id="A")]
    threads, gaps = build_threads(letters)
    assert [l.doc_id for l in threads[0]] == ["S", "A"]
    assert gaps == []


def test_out_of_order_reply_is_flagged():
    late = parse_letter(REPLY, doc_id="A")
    late.responds_to = (2024, 3, 6)
    late.responds_to_raw = "March 6, 2024"
    letters = [late, parse_letter(STAFF, doc_id="S")]
    _, gaps = build_threads(letters)
    assert len(gaps) == 1
    assert "不在语料中" in gaps[0].reason


def test_hard_wrapped_date_is_recovered():
    """真实函件在 72 列硬换行，日期会被拆成两行。"""
    text = REPLY.replace("dated April 2, 2024", "dated April\n2, 2024")
    letter = parse_letter(text, doc_id="A")
    assert letter.responds_to == (2024, 4, 2)


def test_confidential_letter_goes_to_legal_not_compliance():
    """Rule 83 请求的意义就是正文不能被普通审批人看到。"""
    assert approval_route(parse_letter(REPLY, doc_id="A")) == "legal"
    assert approval_route(parse_letter(STAFF, doc_id="S")) == "compliance"
