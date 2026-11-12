"""准入 / 限流 / 审批：常驻 agent 的三个安全阀。

这是本项目真正的产品 —— 不是「agent 能回消息」，而是「agent 只在该回的时候回、
对不该直接做的事先问人」。每一条拒绝都必须给出可读理由，否则运维无法排查。
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .channels import Inbound

# 风险动作：命中即需人工审批（不是禁止，是「先问」）
RISK_PATTERNS = [
    (re.compile(r"(退款|付款|转账|打款|refund|wire|payment)", re.I), "money"),
    (re.compile(r"(删除|删掉|销户|drop\s+table|delete\s+all)", re.I), "destructive"),
    (re.compile(r"(密码|验证码|身份证|password|otp|ssn|id\s*card)", re.I), "secrets"),
    (re.compile(r"(合同|报价|commit|签约|invoice)", re.I), "commercial"),
]


@dataclass
class Decision:
    allow: bool
    reason: str = ""
    needs_approval: bool = False
    risk: str = ""

    def __bool__(self) -> bool:  # 让 `if decision:` 读起来自然
        return self.allow


@dataclass
class Approval:
    approval_id: str
    thread_id: str
    text: str
    risk: str
    created_at: float
    status: str = "pending"      # pending | approved | rejected
    decided_by: str = ""


class Policy:
    def __init__(self, allowlist: set[str] | None = None,
                 rate_limit: int = 6, window_seconds: int = 60,
                 external_needs_approval: bool = True):
        self.allowlist = allowlist or set()
        self.rate_limit = rate_limit
        self.window = window_seconds
        self.external_needs_approval = external_needs_approval
        self._hits: dict[str, deque] = defaultdict(deque)
        self.audit: list[dict] = []
        self.approvals: list[Approval] = []
        self._seq = 0

    # ---- 入口 ----
    def check_inbound(self, inbound: Inbound) -> Decision:
        if self.allowlist and inbound.sender not in self.allowlist:
            self._log(inbound, "blocked", "sender 不在白名单")
            return Decision(False, f"发件人 {inbound.sender} 不在白名单")
        if not inbound.text.strip():
            self._log(inbound, "blocked", "空消息")
            return Decision(False, "空消息")
        if not self._take_token(inbound.sender):
            self._log(inbound, "throttled", "超出速率")
            return Decision(False, f"发件人 {inbound.sender} 超出 {self.rate_limit}/{self.window}s 速率限制")
        self._log(inbound, "accepted", "")
        return Decision(True)

    # ---- 出口 ----
    def check_outbound(self, inbound: Inbound, text: str) -> Decision:
        if inbound.is_external and self.external_needs_approval:
            return self._queue(inbound, text, "external")
        for pattern, kind in RISK_PATTERNS:
            if pattern.search(text):
                return self._queue(inbound, text, kind)
        return Decision(True)

    def _queue(self, inbound: Inbound, text: str, risk: str) -> Decision:
        self._seq += 1
        aid = f"AP-{self._seq:04d}"
        self.approvals.append(Approval(aid, inbound.thread_id, text, risk, time.time()))
        self._log(inbound, "pending_approval", f"{aid} risk={risk}")
        return Decision(True, f"已进入审批队列 {aid}（{risk}）", needs_approval=True, risk=risk)

    def decide(self, approval_id: str, approved: bool, by: str = "operator") -> Approval:
        for a in self.approvals:
            if a.approval_id == approval_id:
                a.status = "approved" if approved else "rejected"
                a.decided_by = by
                self.audit.append({"event": "approval_decided", "id": approval_id,
                                   "status": a.status, "by": by})
                return a
        raise KeyError(approval_id)

    def pending(self) -> list[Approval]:
        return [a for a in self.approvals if a.status == "pending"]

    # ---- 内部 ----
    def _take_token(self, sender: str) -> bool:
        now = time.time()
        q = self._hits[sender]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.rate_limit:
            return False
        q.append(now)
        return True

    def _log(self, inbound: Inbound, result: str, note: str) -> None:
        self.audit.append({
            "channel": inbound.channel, "thread": inbound.thread_id, "sender": inbound.sender,
            "result": result, "note": note,
        })
