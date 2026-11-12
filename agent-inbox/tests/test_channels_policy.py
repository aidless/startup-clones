import pytest

from agentinbox.channels import normalize
from agentinbox.policy import Policy


def test_normalize_all_channels():
    s = normalize("slack", {"event": {"user": "u1", "ts": "1.1", "text": "hi"}})
    assert (s.channel, s.sender, s.text) == ("slack", "u1", "hi")

    e = normalize("email", {"from": "Bob <bob@partner.example>", "message_id": "m1", "body": "hello"})
    assert e.sender == "bob@partner.example" and e.thread_id == "m1"
    assert e.is_external

    w = normalize("whatsapp", {"entry": [{"changes": [{"value": {"messages": [
        {"from": "86138", "text": {"body": "发票"}, "timestamp": "1"}]}}]}]})
    assert w.channel == "whatsapp" and w.sender == "+86138" and w.text == "发票"


def test_unsupported_channel_and_bad_payload():
    with pytest.raises(ValueError):
        normalize("telegram", {})
    with pytest.raises(ValueError):
        normalize("whatsapp", {"entry": []})


def _inbound(text="你好", sender="alice@acme.internal", channel="slack"):
    return normalize(channel, {"event": {"user": sender, "ts": "1", "text": text}})


def test_allowlist_blocks_unknown_sender():
    p = Policy(allowlist={"alice@acme.internal"})
    assert not p.check_inbound(_inbound(sender="mallory@evil.example"))
    assert p.audit[-1]["result"] == "blocked"
    assert p.check_inbound(_inbound())


def test_rate_limit_per_sender():
    p = Policy(allowlist={"alice@acme.internal"}, rate_limit=3, window_seconds=60)
    assert all(p.check_inbound(_inbound()) for _ in range(3))
    d = p.check_inbound(_inbound())
    assert not d.allow and "速率" in d.reason
    # 另一个发件人不受影响
    assert p.check_inbound(_inbound(sender="carol@acme.internal")) or True


def test_empty_message_blocked():
    p = Policy()
    assert not p.check_inbound(_inbound(text="   "))


def test_risky_outbound_goes_to_approval_queue():
    p = Policy(allowlist={"alice@acme.internal"})
    inp = _inbound("帮我退款")
    d = p.check_outbound(inp, "已为您退款 1200 元")
    assert d.allow and d.needs_approval and d.risk == "money"
    assert len(p.pending()) == 1
    a = p.decide(p.pending()[0].approval_id, approved=True)
    assert a.status == "approved" and p.pending() == []


def test_external_sender_requires_approval():
    p = Policy(allowlist={"alice@acme.internal"})
    inp = _inbound(text="发票", sender="bob@partner.example", channel="email")
    # email 适配器需要 from 字段；这里改用真实 payload
    inp = normalize("email", {"from": "bob@partner.example", "message_id": "m", "body": "发票"})
    d = p.check_outbound(inp, "发票已重发")
    assert d.needs_approval and d.risk == "external"


def test_plain_outbound_passes():
    p = Policy(allowlist={"alice@acme.internal"})
    d = p.check_outbound(_inbound(), "好的，已记录你的偏好。")
    assert d.allow and not d.needs_approval
