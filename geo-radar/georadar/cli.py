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

from . import __version__
from . import prompts, providers, store, view
from .extract import find_mentions
from .models import Run


def _brands_payload(view) -> list[dict]:
    """品牌行与人读表格同源：都从 BrandStats 取，不另算一遍。"""
    return [
        {
            "name": name,
            "mentions": st.mentions,
            "share_of_voice": round(st.share_of_voice, 6),
            "prompts_seen": st.prompts_seen,
            "avg_position": st.avg_position,
            "sentiment": round(st.sentiment, 4),
        }
        for name, st in sorted(view.stats.items(), key=lambda kv: (-kv[1].mentions, kv[0]))
    ]


def _run_payload(view) -> dict:
    return {
        "run_id": view.run.run_id,
        "brand": view.run.brand,
        "category": view.run.category,
        "competitors": list(view.run.competitors),
        "provider": view.run.provider,
        "created_at": view.run.created_at,
        "prompts_total": view.prompts_total,
        "answers": len(view.answers),
        "mentions": len(view.mentions),
        "brands": _brands_payload(view),
    }


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
    # 落库后从库里读回来装配：内存里的 stats/answers 与 `report --run-id` 走同一个
    # 函数（georadar.view.assemble），两条路径不再各拼一份。副作用是这里打印的
    # 就是「真正落盘、以后还能复现」的那份数，若落库有丢失会当场看得见。
    try:
        v = view.load_view(conn, run.run_id)
        markdown = v.markdown
    except BaseException:
        # 装配/渲染失败就把这次 run 撤掉：否则用户库里躺着一条打不开的报告，
        # 而 `report --run-id` 连自己都渲染不出来（demo 曾是这么崩的）。
        store.delete_run(conn, run.run_id)
        raise

    if args.json:
        payload = _run_payload(v)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(markdown + "\n")
            payload["report_path"] = args.out
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"run_id   : {run.run_id}")
    print(f"prompts  : {len(ps)} × {args.repeat} = {len(v.answers)} 次回答")
    print(f"mentions : {len(v.mentions)}")
    for name, s in sorted(v.stats.items(), key=lambda kv: (-kv[1].mentions, kv[0])):
        print(f"  {name:<24} mentions={s.mentions:<4} sov={s.share_of_voice:.1%} "
              f"avg_pos={s.avg_position}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            # 末尾补换行：否则同一份报表「落盘文件」与「report 打印」只差一个
            # 行尾换行符，diff 会报 43c43，看上去像两份报表不一样。
            f.write(markdown + "\n")
        print(f"report   : {args.out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
    v = view.load_view(conn, args.run_id)
    if args.json:
        print(json.dumps(_run_payload(v), ensure_ascii=False, indent=2))
        return 0
    print(v.markdown)
    return 0


DEMO_ARGS = [
    "run", "--brand", "Acme", "--category", "AI SRE",
    "--competitors", "Traversal,Rootly", "--provider", "mock",
    "--model", "mock-1", "--repeat", "3", "--limit", "12",
    "--out", "reports/acme-weekly.md",
]


def cmd_demo(args: argparse.Namespace) -> int:
    """零配置演示：走 `run` 的同一套解析器，不再手搓 Namespace。

    手搓过一次，漏了 `--json` 字段，于是 `cmd_run` 在 `save_run` 之后抛
    `AttributeError: 'Namespace' object has no attribute 'json'`：命令退出 1，
    库里却已经写进一次 run。命令行参数只该有一处定义。
    """
    import os
    os.makedirs("reports", exist_ok=True)
    rc = main(DEMO_ARGS)
    if rc == 0:
        with open("reports/acme-weekly.md", encoding="utf-8") as f:
            print("\n" + "─" * 60 + "\n")
            print(f.read()[:1200])
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="georadar", description="AI 搜索引擎可见性监测")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="跑一轮探测")
    r.add_argument("--brand", required=True)
    r.add_argument("--category", required=True)
    r.add_argument("--competitors", default="")
    r.add_argument("--provider", default="mock",
                   choices=["mock", "ollama", "openai", "openai-compat", "deepseek", "kimi",
                            "vllm", "magpie"],
                   help="ollama 走本机 127.0.0.1:11434；magpie 走本机网关，都不需要 key")
    r.add_argument("--model", default="mock-1")
    r.add_argument("--repeat", type=int, default=3)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--db", default="georadar.db")
    r.add_argument("--out", default="")
    r.add_argument("--json", action="store_true", help="输出 JSON")
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="重新渲染历史 run")
    p.add_argument("--db", default="georadar.db")
    p.add_argument("--run-id", required=True)
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_report)

    d = sub.add_parser("demo", help="零配置演示")
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
