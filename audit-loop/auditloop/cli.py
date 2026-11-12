"""命令行入口。

    python -m auditloop.cli demo
    python -m auditloop.cli run --entity "Acme Industrial" --out out/workpaper.xlsx
"""
from __future__ import annotations

import argparse
import sys

from . import checks, fixtures
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auditloop", description="审计底稿自动化")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮审计程序")
    r.add_argument("--entity", default="Acme Industrial")
    r.add_argument("--out", default="out/workpaper.xlsx")
    r.set_defaults(func=cmd_run)
    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
