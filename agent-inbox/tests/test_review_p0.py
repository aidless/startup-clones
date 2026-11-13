"""审查报告 P0 三条 + 两条 P1 的复现测试（2026-11-12 审查）。

agent-inbox 的产品价值全在「边界」：
- 外部消息必须人工审批（P0-7 显示名伪装把这条整条抹掉）
- 未配置白名单时不能默认全放行（P0-8 fail-open）
- 资金动作用同义说法也要拦（P0-9 改个说法就绕过）
- 回传的 approval_id 必须能直接交给 decide()（P1 router 从人读文案抠 id）
- 已终态的审批不能被改判（P1 decide 不校验状态）
"""
from __future__ import annotations

import pytest

from agentinbox.channels import Inbound, normalize, parse_email
from agentinbox.policy import Policy
from agentinbox.memory import Memory
from agentinbox.router import Router


# ---- P0-7：显示名伪装 ----

def test_display_name_spoofing_does_not_impersonate_internal_sender():
    inp = parse_email({
        "from": '"Alice <alice@acme.example>" <attacker@evil.example>',
        "message_id": "m", "body": "客户名单见附件",
    })
    assert inp.sender == "attacker@evil.example", f"必须取真正的 addr-spec，实际 {inp.sender!r}"
    assert inp.is_external is True


def test_plain_display_name_still_parsed():
    # 正对照：正常写法 "Bob <bob@partner.example>" 必须仍然解析成地址
    inp = parse_email({"from": "Bob <bob@partner.example>", "message_id": "m", "body": "hi"})
    assert inp.sender == "bob@partner.example"
    assert inp.is_external is True


def test_internal_sender_not_marked_external():
    # 正对照：内部域不能因为修了伪装而被判成外部
    inp = parse_email({"from": "alice@acme.example", "message_id": "m", "body": "hi"})
    assert inp.sender == "alice@acme.example"
    assert inp.is_external is False


def test_spoofed_from_goes_through_approval():
    inp = parse_email({
        "from": '"Alice <alice@acme.example>" <attacker@evil.example>',
        "message_id": "m", "body": "hi",
    })
    d = Policy(allowlist={"alice@acme.example"}).check_outbound(inp, "客户名单见附件")
    assert d.needs_approval is True, f"外部发件人的回复必须走审批：{d}"


# ---- P0-8：空白名单 fail-open ----

def test_blank_allowlist_denies_by_default():
    d = Policy().check_inbound(normalize(
        "email", {"from": "anyone@evil.example", "message_id": "m", "body": "hi"}))
    assert d.allow is False, "未配置白名单 ≠ 放行任何人"
    assert "白名单" in d.reason


def test_open_mode_is_explicit_not_accidental():
    d = Policy(open_mode=True).check_inbound(normalize(
        "email", {"from": "anyone@evil.example", "message_id": "m", "body": "hi"}))
    assert d.allow is True


# ---- P0-9：风险动作同义说法 ----

@pytest.mark.parametrize("text", [
    "把这 1200 元汇给供应商账户",
    "转1200给客户",
    "把这笔钱退回原账户",
    "还给客户 500 元",
    "打 3 万到他卡上",
    "wire 5000 to the supplier",
    "send 1200 to the customer",
])
def test_money_synonyms_need_approval(text):
    inp = Inbound("email", "t", "alice@acme.example", "x", "t")
    d = Policy(allowlist={"alice@acme.example"}).check_outbound(inp, text)
    assert d.needs_approval is True, f"资金动作「{text}」必须进审批"
    assert d.risk == "money"


def test_non_money_text_still_passes():
    inp = Inbound("email", "t", "alice@acme.example", "x", "t")
    d = Policy(allowlist={"alice@acme.example"}).check_outbound(inp, "好的，已记录你的偏好。")
    assert d.allow and not d.needs_approval


# ---- P1：router 回传的 approval_id 必须是真 id ----

def test_router_returns_usable_approval_id():
    p = Policy(allowlist={"alice@acme.example"})
    r = Router(p, Memory(), lambda i, ctx: "已为您退款 1200 元")
    out = r.handle("email", {"from": "alice@acme.example", "message_id": "m", "body": "退款"})
    assert out.delivered is False
    real_ids = [a.approval_id for a in p.pending()]
    assert out.approval_id in real_ids, f"回传 {out.approval_id!r}，队列里只有 {real_ids}"
    p.decide(out.approval_id, approved=True)      # 不抛 KeyError 即可


# ---- P1：终态不可改判 ----

def test_terminal_approval_cannot_be_flipped():
    p = Policy(allowlist={"alice@acme.example"})


    inp = Inbound("email", "t", "alice@acme.example", "x", "t")
    p.check_outbound(inp, "已为您退款 1200 元")
    aid = p.pending()[0].approval_id
    assert p.decide(aid, approved=False).status == "rejected"
    with pytest.raises(ValueError):
        p.decide(aid, approved=True, by="attacker")
    assert p.pending() == []


# ---- P1：限流键不能只用可伪造的 sender ----

def test_flood_with_rotating_senders_is_throttled():
    p = Policy(open_mode=True, rate_limit=3, window_seconds=60)
    allowed = sum(
        p.check_inbound(normalize("email", {"from": f"u{i}@evil{i}.example",
                                           "message_id": f"m{i}", "body": "hi"})).allow
        for i in range(100)
    )
    assert allowed <= 6, f"伪造 100 个 From 应被全局兜底限流，实际放行 {allowed}"


def test_normal_single_sender_under_limit_passes():
    p = Policy(allowlist={"alice@acme.example"}, rate_limit=5, window_seconds=60)
    inp = Inbound("email", "t", "alice@acme.example", "hi", "t")
    for _ in range(5):
        assert p.check_inbound(inp).allow
