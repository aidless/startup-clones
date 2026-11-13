"""审查报告 P1（agent-inbox）剩余两处的复现测试（2026-11-12 审查）。

1. 审批号按实例自增：重启 / 多实例后从 AP-0001 重来，跨实例撞号，
   一封信的审批结论会落到另一封信头上。
2. 保密标记大小写敏感：正文写小写 `rule 83 and 17 cfr 200.83`（真实函件里
   抬头常被 OCR 或人工录入成小写）→ confidential=False → 泄密风险函件
   被路由到 compliance 而不是 legal。
"""
from __future__ import annotations

import pytest

from agentinbox.corresp import CONFIDENTIAL_RES, approval_route, parse_letter
from agentinbox.policy import Inbound, Policy


# ---------------- P1-a 审批号跨实例唯一 ----------------

def _inbound(thread="T-1", sender="alice@acme.example", text="hi"):
    # is_external 是 property（按发件域判定），不是构造参数
    return Inbound(channel="slack", thread_id=thread, sender=sender, text=text, ts="0")


def test_approval_ids_unique_across_instances():
    a, b = Policy(open_mode=True), Policy(open_mode=True)
    ids = []
    for _ in range(3):
        ids.append(a.check_outbound(_inbound(), "把这 1200 元汇给供应商账户").approval_id)
        ids.append(b.check_outbound(_inbound(), "把这 1200 元汇给供应商账户").approval_id)
    assert len(set(ids)) == len(ids), f"两个实例撞号：{ids}"


def test_restarted_policy_does_not_reissue_old_ids():
    """重启 = 新进程新实例。旧号若被复用，日志里两条审批记录指向同一号。"""
    first = Policy(open_mode=True).check_outbound(_inbound(), "退款给客户").approval_id
    second = Policy(open_mode=True).check_outbound(_inbound(), "退款给客户").approval_id
    assert first != second


def test_decide_rejects_foreign_approval_id():
    a, b = Policy(open_mode=True), Policy(open_mode=True)
    aid = a.check_outbound(_inbound(), "把这笔钱退回原账户").approval_id
    b.check_outbound(_inbound(), "把这笔钱退回原账户")
    with pytest.raises(KeyError):
        b.decide(aid, True)      # b 不该认领 a 的号


def test_same_instance_ids_still_readable():
    # 正对照：同一实例内号仍然可读、可递增、能 decide
    p = Policy(open_mode=True)
    d = p.check_outbound(_inbound(), "退款给客户 500 元")
    assert d.approval_id.startswith("AP-")
    assert p.decide(d.approval_id, True).status == "approved"


# ---------------- P1-b 保密标记大小写 ----------------

_HEADER = """VIA EDGAR

Rule 83 Confidential Treatment Request by {who}

Re:  Acme Corporation
    Form 10-K for the fiscal year ended September 30, 2025
    File No. 001-36743

Dear Sir or Madam:

We request confidential treatment.
"""


@pytest.mark.parametrize("marker", [
    "Rule 83",
    "rule 83",
    "RULE 83",
    "17 C.F.R. § 200.83",
    "17 cfr 200.83",
    "17 C.F.R. 200.83",
    "FOIA CONFIDENTIAL TREATMENT",
    "foia confidential treatment",
])
def test_confidential_marker_case_insensitive(marker):
    who = "Acme Corporation" if "rule" in marker.lower() or "cfr" in marker.lower() else "Acme"
    text = _HEADER.format(who=who).replace("Rule 83 Confidential Treatment Request",
                                           marker + " Request")
    letter = parse_letter(text, doc_id="A")
    assert letter.confidential is True, f"标记 {marker!r} 未被认出"
    assert approval_route(letter) == "legal"


def test_plain_letter_is_not_confidential():
    # 正对照：没有标记的普通函件仍是 compliance
    plain = _HEADER.format(who="Acme").replace("Rule 83 Confidential Treatment Request", "Response to Comments")
    letter = parse_letter(plain, doc_id="P")
    assert letter.confidential is False
    assert approval_route(letter) == "compliance"


def test_marker_regexes_are_precompiled():
    assert all(hasattr(r, "search") for r in CONFIDENTIAL_RES)
