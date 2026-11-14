"""路由：入站 → 准入 → 上下文 → 应答 → 出口审批 → 出站。

一个常驻 agent 的核心循环就这么长。多出来的复杂度全在 policy 与 memory 里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .channels import Inbound, normalize
from .memory import Memory
from .policy import Decision, Policy


@dataclass
class Outbound:
    channel: str
    thread_id: str
    text: str
    delivered: bool
    approval_id: str = ""
    risk: str = ""      # 出口判定的风险档（money / external / …），查询面要回答「为什么」
    reason: str = ""


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
        self.last_inbound: Decision | None = None   # 入站判定原文（拒绝理由要能原样取回）

    def handle(self, channel: str, payload: dict) -> Outbound | None:
        return self.handle_inbound(normalize(channel, payload))

    def handle_inbound(self, inbound: Inbound) -> Outbound | None:
        """`handle` 拆出这一步，是为了让命令行能直接喂一条 Inbound 而不伪造 webhook 载荷
        ——两份「入站→应答→审批」的实现迟早会分叉。"""
        decision = self.policy.check_inbound(inbound)
        self.last_inbound = decision
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
            # 不要从人读文案里抠 id：原实现 reason.split(" ")[1] 拿到的是
            # "AP-0001（money）"，拿去 decide() 直接 KeyError。
            approval_id = out_decision.approval_id
        return Outbound(inbound.channel, inbound.thread_id, reply, delivered, approval_id,
                        out_decision.risk, out_decision.reason)
