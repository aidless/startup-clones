"""命令行入口。

    python -m auditloop.cli demo
    python -m auditloop.cli run --entity "Acme Industrial" --out out/workpaper.xlsx
    python -m auditloop.cli analytics --facts tests/fixtures/acme_annual.json [--json]
    python -m auditloop.cli init [--dir out/init]
    python -m auditloop.cli analytics --facts out/init/facts.xlsx
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
from .excel import read_facts, write_facts_template
from .models import COMPLETENESS, CUTOFF, EXISTENCE, VALUATION
from .workpaper import write_workpaper

POLICY_AR_90 = 90


def build_run(entity: str = "Acme Industrial") -> AuditRun:
    ents = fixtures.entries()
    lines = fixtures.bank_lines()
    invs = fixtures.invoices()
    period_end = fixtures.PERIOD_END
    as_of = fixtures.AS_OF
    # rec / buckets 必须**在闭包里**算：原先它们在 register 之前求值，
    # 一行脏数据就让 build_run 直接抛 traceback 退出，engine 的
    # try/except → status=degraded 这条防线根本没被触达。
    # 前置计算搬进各自的步骤后，register 才是唯一的执行入口。

    def bank_recon():
        rec = checks.reconcile_bank(ents, lines)
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
        buckets = checks.ar_aging(invs, as_of)
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


def _finding_payload(f) -> dict:
    return {"check": f.check, "assertion": f.assertion, "ref": f.ref,
            "severity": f.severity, "detail": f.detail, "amount": f.amount}


def run_payload(run) -> dict:
    """一轮审计的结构化形状：steps 是「跑了什么」，exceptions 是「要人看什么」。"""
    return {
        "entity": run.entity,
        "period_end": run.period_end.isoformat(),
        "status": run.status,
        "steps": [
            {
                "name": r.name,
                "assertion": r.assertion,
                "status": r.status,
                "error": r.error,
                "rows_examined": r.rows_examined,
                "findings": len(r.findings),
            }
            for r in run.results
        ],
        "exceptions": [_finding_payload(f) for f in run.findings],
    }


def cmd_run(args: argparse.Namespace) -> int:
    run = build_run(args.entity)
    if args.json:
        if args.out:
            print(json.dumps(run_payload(run), ensure_ascii=False, indent=2))
            detail = {
                "总账分录": [f"{e.entry_id} {e.date} {e.account} {e.amount:,.2f} {e.memo}" for e in fixtures.entries()],
                "银行流水": [f"{b.line_id} {b.date} {b.amount:,.2f} {b.memo}" for b in fixtures.bank_lines()],
                "发票": [f"{i.invoice_id} {i.customer} {i.amount:,.2f} 到期 {i.due_date}" for i in fixtures.invoices()],
            }
            write_workpaper(run, args.out, detail)
        else:
            print(json.dumps(run_payload(run), ensure_ascii=False, indent=2))
        return 0
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
    # 显式给全 cmd_run 会读的字段：漏一个就是 AttributeError，
    # 而且是在 6 个程序都跑完之后崩在打印分支上（用户连「哪步坏了」都看不到）。
    ns = argparse.Namespace(entity="Acme Industrial", out="out/workpaper.xlsx",
                            json=False)
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
        line = f"{head} 本期 — 上期 — 变化 — 判定 数据不足"
        # 为什么「数据不足」也要带原因：只印四个字，现场无从判断是缺列、
        # 缺上期，还是数据本身有问题 —— 三种情况的补救办法完全不同。
        if item.detail:
            line += f"  {item.detail}"
        return line
    cur = f"{item.current:.{p}f}"
    prior = "—" if item.prior is None else f"{item.prior:.{p}f}"
    change = "—" if item.change is None else f"{item.change:+.{p}f}"
    line = f"{head} 本期 {cur} 上期 {prior} 变化 {change} 判定 {_verdict(item)}"
    if item.detail:
        line += f"  {item.detail}"
    return line


def cmd_analytics(args: argparse.Namespace) -> int:
    """分析性程序的命令行出口。

    退出码四档（README 的「退出码」一节逐条写明了）：
    0=跑完，至少一条指标判定成立且无异常；1=跑完且有异常；
    2=根本没跑成（文件缺失/JSON 坏了/没有收入列）；
    3=跑完了，但一条指标都没判定成（全部「数据不足」）。

    为什么要第 3 档：0 的含义是「查过了，没问题」。全部指标都算不出来时
    退出码仍是 0，流水线上它与「真查过且干净」长得一模一样 —— 这是审计里
    最贵的一种失败（没查被当成查过）。部分未判定时走 stderr 说明，仍按 0/1。
    """
    # .xlsx 与 .json 走同一个入口：审计师手上是 Excel，脚本里是 JSON，
    # 两种输入必须产出同构的 dict —— 否则「换一种填法结论就变」。
    try:
        payload = read_facts(args.facts)
    except FileNotFoundError:
        print(f"找不到 facts 文件：{args.facts}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"facts 不是合法 JSON：{args.facts}（{exc}）", file=sys.stderr)
        return 2
    except ValueError as exc:
        # Excel 表头/年度坏掉、扩展名不认识、JSON 结构不对，都是「没跑成」
        print(f"facts 内容不可用：{args.facts}（{exc}）", file=sys.stderr)
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
    nothing_judged = bool(items) and len(insufficient) == len(items)

    if args.json:
        print(json.dumps({
            "entity": entity,
            "items": [i.as_dict() for i in items],
            "summary": {"total": len(items), "anomalies": len(anomalies),
                        "insufficient": len(insufficient),
                        "nothing_judged": nothing_judged},
        }, ensure_ascii=False, indent=2))
    else:
        print(f"{entity} · 分析性程序")
        for item in items:
            print(analytics_line(item))
        if anomalies:
            print(f"异常 {len(anomalies)} 项 / 共 {len(items)} 项"
                  f"（未计算 {len(insufficient)} 项）")

    if nothing_judged:
        print(f"一条指标都没判定成：{len(items)} 项全部数据不足（缺列或只有一个财年），"
              f"这份输入给不出任何结论", file=sys.stderr)
        return 3
    if insufficient:
        print(f"未判定 {len(insufficient)} 项 / 共 {len(items)} 项（无可比上期或缺列）",
              file=sys.stderr)
    return 1 if anomalies else 0


def cmd_init(args: argparse.Namespace) -> int:
    """写一张中文表头的填空模板，并把下一步命令原样印出来。

    路径用绝对路径打印：审计师复制这行就能跑，不用自己拼目录。
    """
    target = Path(args.dir) / "facts.xlsx"
    try:
        path = write_facts_template(target)
    except OSError as exc:
        print(f"模板写入失败：{target}（{exc}）", file=sys.stderr)
        return 2
    print(f"模板已写入：{path}")
    print("在 Excel 里把四个示例行换成自家四年数据（空着不填表示该年没有这个数），")
    print(f"填好后运行：auditloop analytics --facts {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auditloop", description="审计底稿自动化")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮审计程序")
    r.add_argument("--entity", default="Acme Industrial")
    r.add_argument("--out", default="out/workpaper.xlsx")
    r.add_argument("--json", action="store_true", help="输出 JSON（不打印底稿正文）")
    r.set_defaults(func=cmd_run)
    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)
    a = sub.add_parser("analytics", help="分析性程序：比率与趋势的逐年复核")
    a.add_argument("--facts", required=True,
                   help="年度序列 Excel（.xlsx，用 init 生成）或 JSON（{\"entity\": ..., \"years\": {...}}）")
    a.add_argument("--json", action="store_true", help="输出结构化结果")
    a.set_defaults(func=cmd_analytics)
    i = sub.add_parser("init", help="生成年度数据填空模板（Excel）")
    i.add_argument("--dir", default="out/init", help="写到哪个目录（默认 out/init）")
    i.set_defaults(func=cmd_init)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
