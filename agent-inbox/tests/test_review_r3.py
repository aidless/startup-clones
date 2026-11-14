"""第三轮审查（R3）两处修复的回归测试。

P1-2 全局令牌在 per-sender 拒绝之前就被扣：一个固定 From 连刷 6 条就能让
      正常发件人吃全局额度（policy.py:92 先于 :95）。
P2-5 出口审批词表没有英文动词 + 货币符号/ISO 代码这一整类：`send $500`
      被当成内部闲聊直接发出。
"""
from __future__ import annotations

import pytest

from agentinbox.policy import Inbound, Policy


def _inbound(sender: str = "alice@acme.example", text: str = "hi") -> Inbound:
    return Inbound(channel="email", thread_id="T-1", sender=sender, text=text, ts="0")


# ---------------- P1-2：被 per-sender 拒的请求不得扣全局桶 ----------------

def test_flooding_sender_does_not_burn_global_bucket():
    """A 刷 6 条（3 过 3 拒）后，B 的第 1 条必须通过。

    旧实现里被 per-sender 拒的那 3 次已经在全局桶里花掉了令牌：
    rate_limit=3 → 全局 6，A 一个人就把全局桶清零，B 直接吃「超出全局」。
    """
    p = Policy(open_mode=True, rate_limit=3, window_seconds=60)
    spammer = _inbound(sender="spammer@evil.example")
    allowed = [p.check_inbound(spammer).allow for _ in range(6)]
    assert allowed[:3] == [True, True, True]
    assert allowed[3:] == [False, False, False], f"超出 per-sender 限流应被拒：{allowed}"

    bob = p.check_inbound(_inbound(sender="bob@acme.example"))
    assert bob.allow, f"正常发件人被刷屏者挤掉了全局额度：{bob.reason}"


def test_single_sender_still_throttled_by_its_own_bucket():
    """正对照：B 自己刷超限仍然被拒（per-sender 桶没有因为上面的改动失效）。"""
    p = Policy(open_mode=True, rate_limit=3, window_seconds=60)
    bob = _inbound(sender="bob@acme.example")
    assert [p.check_inbound(bob).allow for _ in range(3)] == [True, True, True]
    d = p.check_inbound(bob)
    assert not d.allow and "bob@acme.example" in d.reason and "速率" in d.reason


def test_global_bucket_still_caps_rotating_senders():
    """正对照：100 个不同 From 仍被全局桶压到 ≤6（全局保护本身还在）。"""
    p = Policy(open_mode=True, rate_limit=3, window_seconds=60)
    allowed = sum(p.check_inbound(_inbound(sender=f"u{i}@evil{i}.example")).allow
                  for i in range(100))
    assert allowed <= 6, f"伪造 100 个 From 放行了 {allowed} 条"


# ---------------- P2-5：英文动词 + 货币符号/ISO 代码进审批 ----------------

@pytest.mark.parametrize("text", [
    "send $500 to the vendor",
    "pay $1,200 now",
    "wire 500 USD",
    "settle 500 USD with the vendor",
    "transfer 1,000 EUR to the supplier",
    "remit 250 GBP",
    "send 300 usd",
    "pay ¥3,000",
])
def test_english_money_phrasings_need_approval(text):
    p = Policy(open_mode=True)
    d = p.check_outbound(_inbound(sender="bob@acme.example"), text)
    assert d.needs_approval and d.risk == "money", f"{text!r} 被直接放行：{d}"


@pytest.mark.parametrize("text", [
    "把这 1200 元汇给供应商",
    "转1200给客户",
    "还给客户 500 元",
    "退款 1200 元",
    "请把 1200 元退回原账户",
])
def test_chinese_money_phrasings_still_need_approval(text):
    """只加不删：旧词表覆盖的中文说法全部保持原判。"""
    p = Policy(open_mode=True)
    d = p.check_outbound(_inbound(sender="bob@acme.example"), text)
    assert d.needs_approval and d.risk == "money"


@pytest.mark.parametrize("text", [
    "发票能重发吗",
    "账户余额多少",
    "帮我看下上周的工单",
    "这周的报销流程走到哪了",
    "今天的会几点开",
])
def test_plain_internal_chat_is_still_delivered(text):
    """正对照：不含金额指令的内部闲聊照旧直发，不被新词表误伤。"""
    p = Policy(open_mode=True)
    d = p.check_outbound(_inbound(sender="bob@acme.example"), text)
    assert d.needs_approval is False and d.risk == ""
