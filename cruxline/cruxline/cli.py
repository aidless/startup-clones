"""命令行入口。

    python -m cruxline.cli demo
    python -m cruxline.cli judge --traces traces.json
    python -m cruxline.cli calibrate --traces traces.json --labels labels.json
    python -m cruxline.cli diff --before a.json --after b.json
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import fixtures
from .calib import calibrate
from .judge import Judge
from .regress import diff
from .store import add_label, connect, latest_verdicts, load_labels
from .trace import Trace, load_traces


def _read_traces(path: str) -> list[Trace]:
    """读轨迹文件：既接受 JSON 数组，也接受一行一条的 JSONL。

    仓库自带语料是 `data/traces.jsonl`（60 条实录），而这里原先只做
    `json.loads(整份文件)` —— 直接 `JSONDecodeError: Extra data`，
    等于真实语料在命令行上根本判不了（单元测试喂内存对象，从没走过文件）。
    """
    text = open(path, encoding="utf-8").read().strip()
    if text.startswith("["):
        return load_traces(json.loads(text))
    items = [json.loads(line) for line in text.splitlines() if line.strip()]
    return load_traces(items)


def _pass_map(verdicts) -> dict[str, bool]:
    return {v.case_id: v.passed for v in verdicts}


def cmd_judge(args: argparse.Namespace) -> int:
    traces = _read_traces(args.traces)
    judge = Judge(threshold=args.threshold)
    verdicts = judge.score_all(traces)
    conn = connect(args.db)
    latest_verdicts(conn, verdicts)
    for v in verdicts:
        print(v.explain())
    rate = sum(v.passed for v in verdicts) / len(verdicts)
    print(f"\n通过率 {rate:.1%}（{len(verdicts)} 条）")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    traces = _read_traces(args.traces)
    human = json.loads(open(args.labels, encoding="utf-8").read())
    judge_map = _pass_map(Judge(threshold=args.threshold).score_all(traces))
    cal = calibrate(human, judge_map, min_kappa=args.min_kappa)
    print(f"样本 {cal.n} · 一致率 {cal.agreement:.1%} · kappa {cal.kappa:+.3f} · "
          f"门槛 {cal.min_kappa}")
    print(f"人工通过率 {cal.human_pass_rate:.1%} / judge 通过率 {cal.judge_pass_rate:.1%}")
    print(f"结论：{'PASS' if cal.ok else 'BLOCK'} — {cal.diagnosis}")
    return 0 if cal.ok else 2


def cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(open(args.before, encoding="utf-8").read())
    after = json.loads(open(args.after, encoding="utf-8").read())
    rep = diff(before, after)
    print(rep.to_markdown())
    return 0 if rep.verdict != "block" else 2


def cmd_demo(args: argparse.Namespace) -> int:
    judge = Judge(threshold=0.75)
    verdicts = judge.score_all(fixtures.TRACES)
    print("== 逐条判定 ==")
    for v in verdicts:
        print(v.explain())

    conn = connect(":memory:")
    latest_verdicts(conn, verdicts)
    for case_id, passed in fixtures.HUMAN_LABELS.items():
        add_label(conn, case_id, "expert", passed, rationale="主管复核")

    judge_map = _pass_map(verdicts)
    cal = calibrate(load_labels(conn, "expert"), judge_map, min_kappa=0.6)
    print(f"\n== 一致性校准 ==\n样本 {cal.n} · 一致率 {cal.agreement:.1%} · "
          f"kappa {cal.kappa:+.3f}\n结论：{'PASS' if cal.ok else 'BLOCK'} — {cal.diagnosis}")

    print("\n== 版本回归（新版修好 c2/c6，弄坏 c1）==")
    rep = diff(fixtures.HUMAN_LABELS, fixtures.second_run_labels())
    print(rep.to_markdown())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cruxline", description="agent 轨迹评测与版本回归")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", help="用 rubric 打分")
    j.add_argument("--traces", required=True)
    j.add_argument("--threshold", type=float, default=0.75)
    j.add_argument("--db", default="cruxline.db")
    j.set_defaults(func=cmd_judge)

    c = sub.add_parser("calibrate", help="与人工标注比对一致性")
    c.add_argument("--traces", required=True)
    c.add_argument("--labels", required=True)
    c.add_argument("--min-kappa", type=float, default=0.6)
    c.add_argument("--threshold", type=float, default=0.75)
    c.set_defaults(func=cmd_calibrate)

    d = sub.add_parser("diff", help="两版结果对比")
    d.add_argument("--before", required=True)
    d.add_argument("--after", required=True)
    d.set_defaults(func=cmd_diff)

    dm = sub.add_parser("demo", help="零配置演示")
    dm.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
