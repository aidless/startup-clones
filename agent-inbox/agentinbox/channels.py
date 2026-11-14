"""渠道归一化：三种 webhook 形状 → 一个 Inbound。

为什么必须先归一化：每个渠道的 payload 结构完全不同（Slack 是 events.callback、
email 是 MIME 头、WhatsApp 是 entry[].changes[].value.messages[]），
如果业务代码里到处 if channel == ...，加第四个渠道时就会漏掉某个边界。
"""
from __future__ import annotations

import re
from email.utils import getaddresses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# "Bob <bob@x.com>" 与 "\"Alice <alice@acme.example>\" <attacker@evil.example>" 两种写法：
# 前者要取尖括号里的地址；后者尖括号里塞了一个伪装成内部同事的显示名，
# 真正的发件人是最后一个尖括号里的地址。只 search(EMAIL_RE) 会取到第一个像邮箱的子串，
# 于是攻击者被当成内部同事，出口审批整条被绕过。
ANGLE_RE = re.compile(r"<([^<>]+)>")
INTERNAL_DOMAINS = ("@acme.example", "@acme.internal")


@dataclass
class Inbound:
    channel: str            # slack | email | whatsapp | imessage
    thread_id: str
    sender: str
    text: str
    ts: str
    raw: dict = field(default_factory=dict)

    @property
    def is_external(self) -> bool:
        """发件人是否来自组织外部（决定要不要审批）。"""
        return not self.sender.lower().endswith(INTERNAL_DOMAINS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_slack(payload: dict) -> Inbound:
    ev = payload.get("event", payload)
    return Inbound(
        channel="slack",
        thread_id=ev.get("thread_ts") or ev.get("ts", ""),
        sender=ev.get("user", ""),
        text=ev.get("text", ""),
        ts=ev.get("ts", _now()),
        raw=payload,
    )


def sender_address(frm: str) -> str:
    """从 From 头里取真正的地址（addr-spec），不取显示名。

    用标准库按 RFC 5322 解析（docs/BORROWED.md B-4）：自造正则会把注释里的邮箱
    当发件人 —— `From: (support@acme.example) bob@partner.example` 会解析成内部域名。
    From 只允许一个地址；出现多个时取最后一个（与「外层尖括号即真实地址」同一立场，
    伪装写法 `"Alice <alice@acme.example>" <attacker@evil.example>` 因此仍落到 attacker）。
    解析不出地址时退回正则，再不行原样返回（宁可标成可疑，也不要静默变成内部同事）。
    """
    parsed = [addr for _, addr in getaddresses([frm]) if addr]
    if parsed:
        return parsed[-1].strip()
    m = EMAIL_RE.search(frm)
    return m.group(0) if m else frm.strip()


def parse_email(payload: dict) -> Inbound:
    frm = payload.get("from", "")
    return Inbound(
        channel="email",
        thread_id=payload.get("thread_id") or payload.get("message_id", ""),
        sender=sender_address(frm),
        text=payload.get("body", payload.get("text", "")),
        ts=payload.get("date", _now()),
        raw=payload,
    )


def parse_whatsapp(payload: dict) -> Inbound:
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]
        return Inbound(
            channel="whatsapp",
            thread_id=msg.get("context", {}).get("id") or msg.get("from", ""),
            sender=f"+{msg.get('from', '')}",
            text=msg.get("text", {}).get("body", ""),
            ts=msg.get("timestamp", _now()),
            raw=payload,
        )
    except (KeyError, IndexError) as exc:
        raise ValueError(f"WhatsApp payload 结构不符: {exc}") from exc


def parse_imessage(payload: dict) -> Inbound:
    return Inbound(
        channel="imessage",
        thread_id=payload.get("chat_id", payload.get("sender", "")),
        sender=payload.get("sender", ""),
        text=payload.get("text", ""),
        ts=payload.get("date", _now()),
        raw=payload,
    )


ADAPTERS: dict[str, Callable[[dict], Inbound]] = {
    "slack": parse_slack,
    "email": parse_email,
    "whatsapp": parse_whatsapp,
    "imessage": parse_imessage,
}


def normalize(channel: str, payload: dict) -> Inbound:
    if channel not in ADAPTERS:
        raise ValueError(f"未支持的渠道: {channel}")
    return ADAPTERS[channel](payload)
