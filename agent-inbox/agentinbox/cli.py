"""命令行入口：把一批 webhook 喂进同一个 agent，看准入/审批/记忆怎么动作。

    python -m agentinbox.cli demo
"""
from __future__ import annotations

import argparse
import json
import sys

from .channels import normalize
from .memory import Memory
from .policy import Policy
from .router import Directory, Router


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
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
