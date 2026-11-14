"""命令行入口。

    python -m auditloop.cli demo
    python -m auditloop.cli run --entity "Acme Industrial" --out out/workpaper.xlsx
    python -m auditloop.cli analytics --facts tests/fixtures/acme_annual.json [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import checks, fixtures
from .analytics import assess, series_from_years
from .engine import AuditRun
from .models import COMPLETENESS, CUTOFF, EXISTENCE, VALUATION
from .workpaper import write_workpaper

POLICY_AR_90 = 90


def build_run(entity: str = "Acme Industrial") -> AuditRun:
    ents = fixtures.entries()
    lines = fixtures.bank_lines()
    invs = fixtures.invoices()
    period_end = fixtures.PERIOD_END
    as_of = fixtures.AS_OF
    rec = checks.reconcile_bank(ents, lines)
    buckets = checks.ar_aging(invs, as_of)

    def bank_recon():
        out = []
        for e, b in rec.amount_diff:
            out.append(checks.Finding(
                "bank_recon", EXISTENCE, ref=e.entry_id, severity="medium",
                detail=f"日期差异 {abs((b.date - e.date).days)} 天，可能为未达账项", amount=e.amount))
        for b in rec.unmatched_bank:
            out.append(checks.Finding("bank_recon", COMPLETENESS, ref=b.line_id, severity="medium",
                                      detail=f"银行已记、企业未记：{b.memo}", amount=b.amount))
        for e in rec.unmatched_gl:
            out.append(checks.Finding("bank_recon", EXISTENCE, ref=e.entry_id, severity="low",
                                      detail=f"企业已记、银行未见：{e.memo}", amount=e.amount))
        return out

    def aging():
        out = []
        for b in buckets:
            if b.label == ">90" and b.invoices:
                out.append(checks.Finding(
                    "ar_aging", VALUATION, ref=",".join(i.invoice_id for i in b.invoices),
                    severity="medium",
                    detail=f"逾期 {POLICY_AR_90} 天以上 {len(b.invoices)} 笔，合计 {b.total:,.2f}，需评估坏账准备",
                    amount=b.total))
        return out

    return (
        AuditRun(entity=entity, period_end=period_end)
        .register("bank_recon", EXISTENCE, bank_recon, rows=lambda: len(ents) + len(lines))
        .register("ar_aging", VALUATION, aging, rows=lambda: len(invs))
        .register("revenue_cutoff", CUTOFF,
                  lambda: checks.revenue_cutoff(invs, period_end), rows=lambda: len(invs))
        .register("duplicate_payment", EXISTENCE,
                  lambda: checks.duplicate_payments(ents), rows=lambda: len(ents))
        .register("ar_sanity", VALUATION,
                  lambda: checks.ar_negative_or_zero(invs), rows=lambda: len(invs))
        .register("ar_completeness", COMPLETENESS,
                  lambda: checks.missing_due_date(invs), rows=lambda: len(invs))
    ).run()


def cmd_run(args: argparse.Namespace) -> int:
    run = build_run(args.entity)
    print(run.to_markdown())
    if args.out:
        detail = {
            "总账分录": [f"{e.entry_id} {e.date} {e.account} {e.amount:,.2f} {e.memo}" for e in fixtures.entries()],
            "银行流水": [f"{b.line_id} {b.date} {b.amount:,.2f} {b.memo}" for b in fixtures.bank_lines()],
            "发票": [f"{i.invoice_id} {i.customer} {i.amount:,.2f} 到期 {i.due_date}" for i in fixtures.invoices()],
        }
        p = write_workpaper(run, args.out, detail)
        print(f"\n底稿已写入：{p}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    ns = argparse.Namespace(entity="Acme Industrial", out="out/workpaper.xlsx")
    return cmd_run(ns)


# 精度与 analytics._PRECISION 一致：两边对同一个数四舍五入到同一位，
# 文本与 --json 才可能逐字对上。
_PRECISION = {"pp": 1, "%": 1, "x": 2}


def _verdict(item) -> str:
    if item.status == "flag":
        return f"异常({item.severity})"
    return "正常" if item.status == "ok" else "数据不足"


def analytics_line(item) -> str:
    """人读输出的一行：指标名 / 本期 / 上期 / 变化 / 判定（异常时附原因）。"""
    p = _PRECISION[item.unit]
    head = f"{item.label}({item.unit})"
    if item.ref:
        head += f" FY{item.ref}"
    if item.status == "insufficient":
        return f"{head} 本期 — 上期 — 变化 — 判定 数据不足"
    cur = f"{item.current:.{p}f}"
    prior = "—" if item.prior is None else f"{item.prior:.{p}f}"
    change = "—" if item.change is None else f"{item.change:+.{p}f}"
    line = f"{head} 本期 {cur} 上期 {prior} 变化 {change} 判定 {_verdict(item)}"
    if item.detail:
        line += f"  {item.detail}"
    return line


def cmd_analytics(args: argparse.Namespace) -> int:
    """分析性程序的命令行出口。

    为什么退出码分三档：这个子命令是给脚本/CI 调用的，「跑完了没」和
    「有没有要人处理的背离」是两件事。0=跑完无异常、1=跑完有异常、
    2=根本没跑成（文件缺失/JSON 坏了/没有收入列）。把 1 压成 0 会让
    背离在流水线上与干净数据无法区分，那是审计里最贵的一种失败。
    """
    try:
        payload = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"找不到 facts 文件：{args.facts}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"facts 不是合法 JSON：{args.facts}（{exc}）", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"facts 读取失败：{args.facts}（{exc}）", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(f"facts 顶层必须是对象：{args.facts}", file=sys.stderr)
        return 2
    try:
        series = series_from_years(payload.get("years"))
    except ValueError as exc:
        print(f"facts 内容不可用：{args.facts}（{exc}）", file=sys.stderr)
        return 2

    entity = payload.get("entity") or "未知主体"
    items = assess(series)
    anomalies = [i for i in items if i.flag]
    insufficient = [i for i in items if i.status == "insufficient"]

    if args.json:
        print(json.dumps({
            "entity": entity,
            "items": [i.as_dict() for i in items],
            "summary": {"total": len(items), "anomalies": len(anomalies),
                        "insufficient": len(insufficient)},
        }, ensure_ascii=False, indent=2))
    else:
        print(f"{entity} · 分析性程序")
        for item in items:
            print(analytics_line(item))
        if anomalies:
            print(f"异常 {len(anomalies)} 项 / 共 {len(items)} 项"
                  f"（未计算 {len(insufficient)} 项）")
    return 1 if anomalies else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auditloop", description="审计底稿自动化")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮审计程序")
    r.add_argument("--entity", default="Acme Industrial")
    r.add_argument("--out", default="out/workpaper.xlsx")
    r.set_defaults(func=cmd_run)
    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)
    a = sub.add_parser("analytics", help="分析性程序：比率与趋势的逐年复核")
    a.add_argument("--facts", required=True,
                   help="年度序列 JSON（{\"entity\": ..., \"years\": {\"2026\": {...}}}）")
    a.add_argument("--json", action="store_true", help="输出结构化结果")
    a.set_defaults(func=cmd_analytics)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
