"""渠道归一化：三种 webhook 形状 → 一个 Inbound。

为什么必须先归一化：每个渠道的 payload 结构完全不同（Slack 是 events.callback、
email 是 MIME 头、WhatsApp 是 entry[].changes[].value.messages[]），
如果业务代码里到处 if channel == ...，加第四个渠道时就会漏掉某个边界。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


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
        return not self.sender.endswith("@acme.internal")


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


def parse_email(payload: dict) -> Inbound:
    frm = payload.get("from", "")
    m = EMAIL_RE.search(frm)
    return Inbound(
        channel="email",
        thread_id=payload.get("thread_id") or payload.get("message_id", ""),
        sender=m.group(0) if m else frm,
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
