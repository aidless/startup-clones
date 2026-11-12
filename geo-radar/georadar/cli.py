"""命令行入口。

    python -m georadar.cli demo
    python -m georadar.cli run --brand Acme --category "AI SRE" \
        --competitors "Traversal,Rootly" --provider mock --repeat 3 --limit 12
    python -m georadar.cli report --db georadar.db --run-id <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import metrics, prompts, providers, report, store
from .extract import find_mentions
from .models import Run


def cmd_run(args: argparse.Namespace) -> int:
    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
    brands = [args.brand] + competitors
    ps = prompts.generate(args.category, limit=args.limit)
    prov = providers.build_provider(args.provider, brands)

    run = Run(
        run_id=store.new_run_id(), brand=args.brand, category=args.category,
        competitors=competitors, provider=prov.name,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    all_mentions = []
    for p in ps:
        for i in range(args.repeat):
            a = prov.complete(p.text, model=args.model, run_index=i)
            a.prompt_id = p.id
            run.answers.append(a)
            all_mentions.extend(find_mentions(a, brands))

    conn = store.connect(args.db)
    store.save_run(conn, run, all_mentions)
    stats = metrics.brand_stats(all_mentions, len(ps))

    print(f"run_id   : {run.run_id}")
    print(f"prompts  : {len(ps)} × {args.repeat} = {len(run.answers)} 次回答")
    print(f"mentions : {len(all_mentions)}")
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1].mentions):
        print(f"  {name:<24} mentions={s.mentions:<4} sov={s.share_of_voice:.1%} "
              f"avg_pos={s.avg_position}")
    if args.out:
        md = report.markdown_report(args.brand, args.category, competitors, stats,
                                    all_mentions, run.answers, len(ps))
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"report   : {args.out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
    run, mentions = store.load_run(conn, args.run_id)
    ids = {a.prompt_id for a in run.answers}
    stats = metrics.brand_stats(mentions, len(ids))
    md = report.markdown_report(run.brand, run.category, run.competitors, stats,
                                mentions, run.answers, len(ids))
    print(md)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    ns = argparse.Namespace(
        db="georadar.db", brand="Acme", category="AI SRE",
        competitors="Traversal,Rootly", provider="mock", model="mock-1",
        repeat=3, limit=12, out="reports/acme-weekly.md",
    )
    import os
    os.makedirs("reports", exist_ok=True)
    rc = cmd_run(ns)
    if rc == 0:
        with open(ns.out, encoding="utf-8") as f:
            print("\n" + "─" * 60 + "\n")
            print(f.read()[:1200])
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="georadar", description="AI 搜索引擎可见性监测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="跑一轮探测")
    r.add_argument("--brand", required=True)
    r.add_argument("--category", required=True)
    r.add_argument("--competitors", default="")
    r.add_argument("--provider", default="mock")
    r.add_argument("--model", default="mock-1")
    r.add_argument("--repeat", type=int, default=3)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--db", default="georadar.db")
    r.add_argument("--out", default="")
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="重新渲染历史 run")
    p.add_argument("--db", default="georadar.db")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_report)

    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
