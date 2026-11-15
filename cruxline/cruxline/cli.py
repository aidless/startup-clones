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
from .rubrics import agent_rubric
from .io import read_traces
from .judge import DEFAULT_RUBRIC
from .store import add_label, connect, latest_verdicts, load_labels


# 轨迹读取统一走 cruxline.io（容器格式 + 字段别名 + 认不出来的记录报错），
# 这里不再保留第二份实现：两份实现迟早对不上（旧版只认 case_id/tool_calls，
# 于是 OpenAI 风格导出的 steps 会被静默读成「零工具调用」并判成 1.0 PASS）。
_read_traces = read_traces


def _pass_map(verdicts) -> dict[str, bool]:
    return {v.case_id: v.passed for v in verdicts}


def _verdict_payload(v) -> dict:
    return {
        "case_id": v.case_id,
        "score": round(v.score, 4),
        "passed": v.passed,
        "threshold": v.threshold,
        "vetoed": list(v.vetoed),
        "criteria": [{"name": d.name, "score": round(d.score, 4),
                      "weight": d.weight, "note": d.note} for d in v.details],
    }


def _rubric_for(name: str):
    """`agent` 是产品自身那套（两个 fatal 项、权重合计 1.0）；`default` 是 judge.py 里的通用五条。

    命令行默认必须走 `agent`：这个工具的用途就是判 agent 轨迹，
    而 `scripts/real_traces.py` 与 README 报的 59/60 用的也是它。
    此前 CLI 写死 `Judge(threshold=...)`，等于用通用 rubric 判 agent 轨迹——
    同一批 60 条轨迹命令行报 34/60，与文档差 25 条，且没有任何提示。
    """
    return agent_rubric() if name == "agent" else DEFAULT_RUBRIC


def cmd_judge(args: argparse.Namespace) -> int:
    traces = read_traces(args.traces)
    judge = Judge(rubric=_rubric_for(args.rubric), threshold=args.threshold)
    verdicts = judge.score_all(traces)
    conn = connect(args.db)
    latest_verdicts(conn, verdicts)
    passed = sum(v.passed for v in verdicts)
    # 通过率只算一次：JSON 与文本共用同一个分子/分母，不各算一遍
    rate = passed / len(verdicts)
    if args.json:
        print(json.dumps({
            "rubric": args.rubric,
            "total": len(verdicts),
            "passed": passed,
            "pass_rate": round(rate, 6),
            "verdicts": [_verdict_payload(v) for v in verdicts],
        }, ensure_ascii=False, indent=2))
        return 0
    for v in verdicts:
        print(v.explain())
    print(f"\n通过率 {rate:.1%}（{len(verdicts)} 条 · rubric={args.rubric}）")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    traces = read_traces(args.traces)
    human = json.loads(open(args.labels, encoding="utf-8").read())
    # 必须用与 judge 同一个 `_rubric_for(args.rubric)`：原先写死
    # `Judge(threshold=...)`（= DEFAULT_RUBRIC），校的是另一把尺，
    # 于是「rubric 不同」被诊断成「judge 偏松/偏严」。
    judge_map = _pass_map(Judge(rubric=_rubric_for(args.rubric),
                                threshold=args.threshold).score_all(traces))
    cal = calibrate(human, judge_map, min_kappa=args.min_kappa)
    print(f"样本 {cal.n} · 一致率 {cal.agreement:.1%} · kappa {cal.kappa:+.3f} · "
          f"门槛 {cal.min_kappa} · rubric={args.rubric}")
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
    j.add_argument("--json", action="store_true", help="输出 JSON")
    j.add_argument("--rubric", choices=["agent", "default"], default="agent",
                   help="agent=产品自身的 agent 轨迹 rubric（默认）；default=judge.py 的通用五条")
    j.set_defaults(func=cmd_judge)

    c = sub.add_parser("calibrate", help="与人工标注比对一致性")
    c.add_argument("--traces", required=True)
    c.add_argument("--labels", required=True)
    c.add_argument("--min-kappa", type=float, default=0.6)
    c.add_argument("--threshold", type=float, default=0.75)
    c.add_argument("--rubric", choices=["agent", "default"], default="agent",
                   help="与 judge 口径一致：agent=产品自身的 agent 轨迹 rubric（默认）；"
                        "default=judge.py 的通用五条")
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
