"""demo：三个 agent 上架 → 一个买家按最小授权安装 → 五次调用（含被拦与重投）→ 出账单。"""

from __future__ import annotations

import sys

from .fixtures import CFO, INVOICE_BOT, RESEARCH
from .meter import Ledger
from .registry import Registry, RegistryError
from .runtime import Runtime


def _handler(name: str):
    outs = {
        "invoice-bot": ("匹配 12 张发票：10 张一致，2 张缺收货单", 1),
        "deck-research": ("摘要已生成，引用 7 条（3 条来自 10-K）", 2400),
        "cfo-copilot": ("本月毛利率 41.2%，环比 -1.8pt；现金可支撑 7.4 个月", 1),
    }

    def run(_rid: str):
        return outs[name]

    return run


def main(argv: list[str] | None = None) -> int:
    reg = Registry()
    ledger = Ledger()
    for m, dev in ((INVOICE_BOT, "northwind-labs"), (RESEARCH, "quill-research"), (CFO, "ledgerly")):
        reg.publish(m, dev)
        ledger.register(m)
    rt = Runtime(reg, ledger)

    print("== 上架 ==")
    for m, dev in ((INVOICE_BOT, "northwind-labs"), (RESEARCH, "quill-research"), (CFO, "ledgerly")):
        print(f"  {m.agent_id}@{m.version}  {m.pricing.kind:<12} digest={m.digest()[:12]}  by {dev}")

    print("\n== 安装（最小授权）==")
    reg.install("acme", "invoice-bot", granted=("fs.read",))
    reg.install("acme", "deck-research", granted=("net.outbound",))
    reg.install("acme", "cfo-copilot", granted=("fs.read", "fs.write"))
    print("  acme 安装 3 个 agent，其中 deck-research 未授予 secrets.read")

    print("\n== 调用 ==")
    calls = [
        ("invoice-bot", ("fs.read",), "req-1001"),
        ("invoice-bot", ("fs.read",), "req-1002"),
        ("deck-research", ("secrets.read",), "req-1003"),   # 缺权限 → 拦
        ("deck-research", ("net.outbound",), "req-1004"),
        ("cfo-copilot", ("fs.read",), "req-1005"),
        ("invoice-bot", ("fs.read",), "req-1001"),          # 重投 → 不重复计费
    ]
    for agent_id, needs, rid in calls:
        ex = rt.execute("acme", agent_id, _handler(agent_id), rid, needs=needs)
        print(ex.render())

    print("\n== 账单 ==")
    devs = {"invoice-bot": "northwind-labs", "deck-research": "quill-research", "cfo-copilot": "ledgerly"}
    print(ledger.statement("acme", devs, fee_pct=20).to_markdown(20))

    print("== 反例：改内容不发新版本 ==")
    try:
        reg.publish(type(INVOICE_BOT)(**{**INVOICE_BOT.__dict__, "description": "偷偷加一个权限"}),
                    "northwind-labs")
    except RegistryError as exc:
        print(f"  已拒绝：{exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
