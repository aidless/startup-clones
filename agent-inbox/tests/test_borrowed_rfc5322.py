"""借用外部机制：From 头按 RFC 5322 解析，不用自造正则（见 docs/BORROWED.md B-4）。

来源：RFC 5322 §3.4 + Python 标准库 email.utils.getaddresses。
自造 EMAIL_RE 在一个真实写法上就错：注释里出现邮箱时，
`From: (support@acme.example) bob@partner.example` 会把注释里的地址当成发件人
→ 出口审批按 acme.example 内部域名放行。
"""
from __future__ import annotations

from agentinbox.channels import sender_address


def test_comment_embedded_address_is_not_the_sender():
    assert sender_address("(support@acme.example) bob@partner.example") == "bob@partner.example"


def test_display_name_disguise_still_resolves_to_outer_address():
    assert sender_address('"Alice <alice@acme.example>" <attacker@evil.example>') == "attacker@evil.example"


def test_plain_display_name():
    assert sender_address("Bob <bob@partner.example>") == "bob@partner.example"


def test_bare_address():
    assert sender_address("bob@partner.example") == "bob@partner.example"


def test_comma_in_display_name_keeps_one_address():
    assert sender_address('"Doe, John" <john@partner.example>') == "john@partner.example"


def test_comment_after_address_still_reads_the_address():
    assert sender_address("bob@partner.example (Bob)") == "bob@partner.example"


def test_unparseable_input_is_returned_stripped_not_silently_dropped():
    assert sender_address("  not-an-address  ") == "not-an-address"
