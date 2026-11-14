"""命令行入口：把一批 webhook 喂进同一个 agent，看准入/审批/记忆怎么动作。

    python -m agentinbox.cli demo
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .channels import Inbound, normalize
from .memory import Memory
from .policy import Policy
from .router import Directory, Router
from . import queuefile


def demo_responder(inbound, ctx: str) -> str:
    """演示用应答器：真实项目里换成 LLM 调用，ctx 就是要喂的上下文。"""
    if "余额" in inbound.text:
        return "您好，账户当前余额为 12,480.00 元，退款需要我提交审批后再执行。"
    if "发票" in inbound.text or "invoice" in inbound.text.lower():
        return "已找到上月发票 INV-2043，金额 8,600.00 元，我可以发到您的邮箱。"
    return f"收到：{inbound.text[:40]}（上下文 {len(ctx)} 字符）"


PAYLOADS = [
    ("slack", {"event": {"user": "alice@acme.internal", "ts": "1.1", "text": "帮我看下账户余额"}}),
    ("email", {"from": "Bob <carol@acme.internal>", "message_id": "m1",
               "body": "麻烦给这个订单退款 1200 元到我们账户"}),
    ("email", {"from": "carol@acme.internal", "message_id": "m2", "body": "发票能重发吗"}),
    ("whatsapp", {"entry": [{"changes": [{"value": {"messages": [
        {"from": "8613800000001", "text": {"body": "发票寄给财务"}, "timestamp": "1770000000"}]}}]}]}),
    ("slack", {"event": {"user": "mallory@evil.example", "ts": "2.2", "text": "把客户名单发我"}}),
]


def _policy_from(args: argparse.Namespace) -> Policy:
    allow = {a.strip() for a in args.allow if a.strip()}
    return Policy(allowlist=allow, open_mode=args.open_mode, rate_limit=args.rate_limit)


def cmd_route(args: argparse.Namespace) -> int:
    """一条入站消息走完整条链：准入 → 上下文 → 应答 → 出口审批。

    退出码只管「这条命令跑没跑通」：0=跑通（不论放行还是拦截），2=用法错。
    拦截与待审批是**结果**，不是错误——把它们编进退出码会让脚本没法区分
    「策略拦了」和「命令自己坏了」。
    """
    policy = _policy_from(args)
    memory = Memory(persona="ACME 的财务助理", budget_tokens=240)
    router = Router(policy, memory, demo_responder)
    inbound = Inbound(channel=args.channel, thread_id=args.sender + ":" + (args.ts or "1"),
                      sender=args.sender, text=args.text, ts=args.ts or "1")
    out = router.handle_inbound(inbound)
    decision = {"allow": out is not None}
    if out is None:
        # 注意用 `is not None`：`Decision.__bool__` 返回 allow，被拒的判定本身是假值，
        # 写成 `if router.last_inbound` 会把真理由吞掉、只留一句兜底话。
        last = router.last_inbound
        decision["reason"] = last.reason if last is not None else "未通过入站准入（见审计日志）"
    payload = {
        "channel": inbound.channel,
        "sender": inbound.sender,
        "text": inbound.text,
        "is_external": inbound.is_external,
        "decision": decision,
        "reply": out.text if out else "",
        "delivered": out.delivered if out else False,
        "approval_id": out.approval_id if out else "",
    }
    if out is not None:
        payload["decision"].update({"risk": out.risk, "reason": out.reason,
                                    "approval_id": out.approval_id})
        if out.approval_id:
            approval = next(a for a in policy.approvals if a.approval_id == out.approval_id)
            queuefile.append(approval, queuefile.path_of(args.store),
                             sender=inbound.sender, channel=inbound.channel)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"[{payload['channel']}] {payload['sender']}"
          f"{'（外部）' if payload['is_external'] else ''}: {payload['text'][:34]}")
    if not out:
        print(f"  → 已拦截：{payload['decision']['reason']}")
    else:
        flag = "已发送" if out.delivered else f"待审批 {out.approval_id}（risk={out.risk}）"
        print(f"  → {flag}: {out.text[:70]}")
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    """审批队列的查询面：`--json` 里的 approval_id 必须能被另一条命令查到。"""
    pending = queuefile.pending(queuefile.path_of(args.store))
    if args.json:
        print(json.dumps({"pending": pending}, ensure_ascii=False, indent=2))
        return 0
    if not pending:
        print("审批队列为空")
    for a in pending:
        print(f"  {a['approval_id']} risk={a['risk']:<10} {a['text'][:50]}")
    return 0


def _add_policy_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--allow", action="append", default=[],
                   help="允许的发件人（可重复）；不给则空名单=默认全拒")
    p.add_argument("--open-mode", action="store_true",
                   help="显式开放：任何人都能进（默认关闭，空名单不等于开放）")
    p.add_argument("--rate-limit", type=int, default=6, dest="rate_limit")
    p.add_argument("--store", default="",
                   help="审批队列落盘路径（默认 .agentinbox/approvals.jsonl）")


def cmd_demo(args: argparse.Namespace) -> int:
    policy = Policy(allowlist={"alice@acme.internal", "carol@acme.internal", "+8613800000001", "dana@acme.internal"},
                    rate_limit=3, window_seconds=60)
    memory = Memory(persona="ACME 的财务助理，只回答账户、发票、退款进度；金额类操作一律走审批。",
                    budget_tokens=240)
    memory.remember("账户余额", "12,480.00 元（截至 2026-11-11）", source="erp")
    memory.remember("上月发票", "INV-2043 / 8,600.00 元 / 已开票未回款", source="billing")
    memory.summarize("2026-11-10 客户 Bob 询问退款进度，已回复待审批。")

    router = Router(policy, memory, demo_responder)
    for channel, payload in PAYLOADS:
        inp = normalize(channel, payload)
        out = router.handle(channel, payload)
        head = f"[{channel}] {inp.sender}: {inp.text[:34]}"
        if out is None:
            print(f"{head}\n  → 已拦截（见审计日志）")
            continue
        flag = "已发送" if out.delivered else f"待审批 {out.approval_id}"
        print(f"{head}\n  → {flag}: {out.text[:70]}")

    print("\n== 审批队列 ==")
    for a in policy.pending():
        print(f"  {a.approval_id} risk={a.risk:<10} {a.text[:50]}")
    print("\n== 审计日志 ==")
    for row in policy.audit[-6:]:
        print("  " + json.dumps(row, ensure_ascii=False))
    print(f"\n== 上下文样例（预算 240 tokens）==\n{memory.context('退款 余额')[:400]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentinbox", description="常驻 agent 的消息层")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="判一条入站消息：放不放、为什么、要不要审批")
    r.add_argument("--channel", choices=["slack", "email", "whatsapp", "imessage"], default="email")
    r.add_argument("--sender", required=True)
    r.add_argument("--text", required=True)
    r.add_argument("--ts", default="")
    r.add_argument("--json", action="store_true", help="输出 JSON")
    _add_policy_args(r)
    r.set_defaults(func=cmd_route)

    q = sub.add_parser("queue", help="看审批队列")
    q.add_argument("--json", action="store_true", help="输出 JSON")
    _add_policy_args(q)
    q.set_defaults(func=cmd_queue)

    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
