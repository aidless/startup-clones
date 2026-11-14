"""准入 / 限流 / 审批：常驻 agent 的三个安全阀。

这是本项目真正的产品 —— 不是「agent 能回消息」，而是「agent 只在该回的时候回、
对不该直接做的事先问人」。每一条拒绝都必须给出可读理由，否则运维无法排查。
"""
from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .channels import Inbound

# 风险动作：命中即需人工审批（不是禁止，是「先问」）
RISK_PATTERNS = [
    # 资金类必须覆盖同义说法：只列「退款/付款/转账/打款」时，
    # 「把这 1200 元汇给供应商」「转1200给客户」「还给客户 500 元」全部直接放行。
    (re.compile(r"(退款|付款|转账|打款|汇款|汇给|汇出|转给|转\s*\d|还给|退回|退给|打钱|付给|"
                r"打\s*(?:\d|[一二三四五六七八九十])|"
                r"refund|wire|payment|remit|transfer|send\s+\d+|pay\s+\d+)", re.I), "money"),
    # 英文动词 + 货币符号/ISO 代码这一整类：只写 `send\s+\d+` 时
    # `send $500 to the vendor` / `pay $1,200 now` / `settle 500 USD` 全部直发，
    # 而 is_external 只看域名后缀 —— 英文写法的内部同事能让 agent 直接对外发钱指令。
    (re.compile(r"\b(?:send|pay|wire|transfer|remit|settle|refund|invoice|charge)\b"
                r"[^.\n]{0,20}?(?:usd|rmb|cny|eur|gbp|jpy|hkd|\$|¥|€|£)\s*[\d,]+", re.I), "money"),
    (re.compile(r"[\$¥€£]\s*[\d,]{2,}"), "money"),
    (re.compile(r"[\d,]+\s*(?:usd|rmb|cny|eur|gbp|jpy|hkd)\b", re.I), "money"),
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
    approval_id: str = ""

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
                 external_needs_approval: bool = True,
                 open_mode: bool = False,
                 global_rate_limit: int = 0):
        """open_mode=True 表示「故意对所有发件人开放」，必须显式声明。

        原先 allowlist 为空时 `if self.allowlist and ...` 直接短路放行——
        忘记配白名单 = 对全世界开放，而配置错误在常驻服务里不会有人发现。
        """
        self.allowlist = set(allowlist or ())
        self.open_mode = open_mode
        # 全局兜底限流：只按 sender 计数时，伪造 100 个 From 就是 100 个独立桶。
        # 全局桶默认是单发件人桶的 2 倍：正常多客户并发不受影响，
        # 但伪造 From 刷量拿到的额度是有限且很小的（10 条测试里放行 ≤6）。
        self.global_rate_limit = global_rate_limit or rate_limit * 2
        self._global: deque = deque()
        self.rate_limit = rate_limit
        self.window = window_seconds
        self.external_needs_approval = external_needs_approval
        self._hits: dict[str, deque] = defaultdict(deque)
        self.audit: list[dict] = []
        self.approvals: list[Approval] = []
        self._seq = 0
        # 审批号必须跨实例唯一。原先每实例从 AP-0001 自增：重启或多实例部署后，
        # 第二封信的 AP-0001 与第一封撞号，decide() 按号查找会落到另一封信上。
        # 加 4 位实例令牌（进程级随机）后，号仍可读、可排序，但不会撞。
        self._instance = secrets.token_hex(2).upper()

    # ---- 入口 ----
    def check_inbound(self, inbound: Inbound) -> Decision:
        if not self.open_mode and inbound.sender not in self.allowlist:
            self._log(inbound, "blocked", "sender 不在白名单")
            why = "白名单未配置，默认全部拒绝（如需开放请显式 open_mode=True）" \
                if not self.allowlist else f"发件人 {inbound.sender} 不在白名单"
            return Decision(False, why)
        if not inbound.text.strip():
            self._log(inbound, "blocked", "空消息")
            return Decision(False, "空消息")
        # 顺序是安全属性：先判「这个发件人自己是否超限」，通过了才扣全局令牌。
        # 反过来的话，被 per-sender 拒掉的重试也已经花掉全局额度 —— 一个固定 From
        # 连刷 6 条就能把全局桶清零，正常发件人全体被挡（与全局桶「2 倍单发件人」的
        # 设计意图相反）。
        if not self._take_token(inbound.sender):
            self._log(inbound, "throttled", "超出速率")
            return Decision(False, f"发件人 {inbound.sender} 超出 {self.rate_limit}/{self.window}s 速率限制")
        if not self._take_global_token():
            self._log(inbound, "throttled", "全局速率")
            return Decision(False, f"超出全局 {self.global_rate_limit}/{self.window}s 速率限制")
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
        aid = f"AP-{self._instance}-{self._seq:04d}"
        self.approvals.append(Approval(aid, inbound.thread_id, text, risk, time.time()))
        self._log(inbound, "pending_approval", f"{aid} risk={risk}")
        return Decision(True, f"已进入审批队列 {aid}（{risk}）",
                        needs_approval=True, risk=risk, approval_id=aid)

    def decide(self, approval_id: str, approved: bool, by: str = "operator") -> Approval:
        for a in self.approvals:
            if a.approval_id == approval_id:
                # 终态不可改判：已批准的不能再被拒，已拒的不能再被批（否则审计日志会自相矛盾）
                if a.status != "pending":
                    raise ValueError(f"{approval_id} 已是终态 {a.status}，不能改判")
                a.status = "approved" if approved else "rejected"
                a.decided_by = by
                self.audit.append({"event": "approval_decided", "id": approval_id,
                                   "status": a.status, "by": by})
                return a
        raise KeyError(approval_id)

    def pending(self) -> list[Approval]:
        return [a for a in self.approvals if a.status == "pending"]

    # ---- 内部 ----
    def _take_global_token(self) -> bool:
        now = time.time()
        while self._global and now - self._global[0] > self.window:
            self._global.popleft()
        if len(self._global) >= self.global_rate_limit:
            return False
        self._global.append(now)
        return True

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
