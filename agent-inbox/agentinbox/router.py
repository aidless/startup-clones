"""路由：入站 → 准入 → 上下文 → 应答 → 出口审批 → 出站。

一个常驻 agent 的核心循环就这么长。多出来的复杂度全在 policy 与 memory 里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .channels import Inbound, normalize
from .memory import Memory
from .policy import Policy


@dataclass
class Outbound:
    channel: str
    thread_id: str
    text: str
    delivered: bool
    approval_id: str = ""


class Directory:
    """一个 agent 可以有多个地址（email / slack / whatsapp），这里只做归属解析。"""

    def __init__(self) -> None:
        self.addresses: dict[str, str] = {}

    def bind(self, address: str, agent_id: str) -> None:
        self.addresses[address] = agent_id

    def agent_for(self, inbound: Inbound) -> str:
        return self.addresses.get(inbound.thread_id, self.addresses.get(inbound.sender, "default"))


Responder = Callable[[Inbound, str], str]


class Router:
    def __init__(self, policy: Policy, memory: Memory, responder: Responder,
                 directory: Directory | None = None):
        self.policy = policy
        self.memory = memory
        self.responder = responder
        self.directory = directory or Directory()

    def handle(self, channel: str, payload: dict) -> Outbound | None:
        inbound = normalize(channel, payload)
        decision = self.policy.check_inbound(inbound)
        if not decision.allow:
            return None

        self.memory.observe(inbound)
        ctx = self.memory.context(query=inbound.text)
        reply = self.responder(inbound, ctx)

        out_decision = self.policy.check_outbound(inbound, reply)
        approval_id = ""
        delivered = True
        if out_decision.needs_approval:
            delivered = False
            approval_id = out_decision.reason.split(" ")[1]
        return Outbound(inbound.channel, inbound.thread_id, reply, delivered, approval_id)
