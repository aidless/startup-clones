"""demo：三个 agent 上架 → 一个买家按最小授权安装 → 五次调用（含被拦与重投）→ 出账单。"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
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


def cmd_demo(args: argparse.Namespace) -> int:
    reg = Registry(args.db)
    ledger = Ledger(args.db)
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


def _developer(value: str) -> tuple[str, str]:
    agent, sep, dev = value.partition("=")
    if not sep or not agent or not dev:
        raise argparse.ArgumentTypeError(f"--developer 要 agent=dev 形式，收到 {value!r}")
    return agent, dev


def _fee_pct(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--fee-pct 要整数，收到 {value!r}")
    if not 0 <= n <= 100:
        raise argparse.ArgumentTypeError(f"--fee-pct 必须在 0..100，收到 {n}")
    return n


def cmd_statement(args: argparse.Namespace) -> int:
    st = Ledger(args.db).issue_statement(
        args.buyer, dict(args.developer or ()), fee_pct=args.fee_pct, request_id=args.request_id)
    if args.json:
        json.dump(st.to_dict(), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(st.to_markdown(st.fee_pct))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="agentstore",
        description="agent 应用商店内核：上架 → 安装 → 调用 → 账单的零配置演示")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", title="子命令")
    d = sub.add_parser("demo", help="跑完整演示（缺省子命令）：3 个 agent 上架 → 6 次调用 → 出账单")
    d.add_argument("--db", default=":memory:",
                   help="把发布与用量记进这个 sqlite 文件（默认 :memory:，跑完即弃）")
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("statement", help="出账：按 buyer 聚合 usage 并分账（--json 给机器读）")
    s.add_argument("--db", required=True, help="商店库（sqlite 文件）")
    s.add_argument("--buyer", required=True, help="买家 id")
    s.add_argument("--fee-pct", type=_fee_pct, default=20, help="平台抽成百分比 0..100（默认 20）")
    s.add_argument("--developer", action="append", type=_developer, metavar="AGENT=DEV",
                   help="agent→开发者归属，可重复；没给的记 unknown")
    s.add_argument("--request-id", default=None,
                   help="出账幂等键（scope 为 buyer）：重复时原样回放首次快照")
    s.add_argument("--json", action="store_true", help="stdout 输出单个 JSON 对象")
    s.set_defaults(func=cmd_statement)
    ap.set_defaults(func=cmd_demo)     # 不带子命令时保持旧行为：直接跑 demo
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
