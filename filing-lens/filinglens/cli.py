"""命令行入口。

    python -m filinglens.cli demo
    python -m filinglens.cli index --html filing.html --facts companyfacts.json --db f.db
    python -m filinglens.cli ask --db f.db "lidar 供应商集中度风险"
    python -m filinglens.cli metric --db f.db revenue
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import edgar, facts as F, fixtures
from .answer import Answerer

SAMPLE_QUESTIONS = [
    "supply chain concentration risk lidar supplier",
    "top customers concentration revenue",
    "revenue",
    "what is the cryptocurrency mining plan in Argentina",
]


def _build(html: str, facts_payload: dict | None, db: str):
    sections, chunks, tables = edgar.parse(html, doc="ACME-10K")
    conn = F.load_companyfacts(facts_payload, db) if facts_payload else None
    return sections, chunks, tables, conn


def cmd_index(args: argparse.Namespace) -> int:
    html = Path(args.html).read_text(encoding="utf-8")
    payload = json.loads(Path(args.facts).read_text(encoding="utf-8")) if args.facts else None
    sections, chunks, tables, conn = _build(html, payload, args.db)
    print(f"sections : {len(sections)}")
    print(f"chunks   : {len(chunks)}")
    print(f"tables   : {len(tables)}")
    if conn:
        n = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        print(f"facts    : {n}")
    print(f"db       : {args.db}")
    return 0


def _answer_payload(question: str, ans) -> dict:
    """一条回答的结构化形状：与人读版本同源（都在 `Response` 上取字段）。"""
    return {
        "question": question,
        "kind": ans.kind,
        "status": ans.status,
        "text": ans.text,
        "confidence": round(ans.confidence, 4),
        "citations": [{"kind": c.kind, "ref": c.ref, "quote": c.quote} for c in ans.citations],
    }


def cmd_ask(args: argparse.Namespace) -> int:
    html = Path(args.html).read_text(encoding="utf-8") if args.html else fixtures.FAKE_10K_HTML
    payload = None
    if args.facts:
        payload = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    elif args.with_fixture_facts:
        payload = fixtures.FAKE_FACTS
    sections, chunks, tables, conn = _build(html, payload, args.db)
    ans = Answerer(chunks, conn)
    if args.json:
        # 单个问题就吐单个对象（调用方不用先拆列表）；多个问题才包一层 answers
        payloads = [_answer_payload(q, ans.ask(q)) for q in args.questions]
        out = payloads[0] if len(payloads) == 1 else {"answers": payloads}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    for q in args.questions:
        print(f"\nQ: {q}")
        print(ans.ask(q).render())
    return 0


def cmd_metric(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    conn = F.load_companyfacts(payload, args.db)
    series = F.annual_series(conn, args.metric)
    if not series:
        print(f"no FY data for {args.metric}")
        return 1
    for f in series:
        print(f"FY{f.fy}  {F.fmt_money(f.val, f.unit)}  [{f.tag}]")
    for fy, chg in F.yoy(series):
        if chg is None:
            print(f"  FY{fy} 不可比（上年为负/零）")
            continue
        print(f"  YoY FY{fy}: {chg:+.1%}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    sections, chunks, tables, conn = _build(fixtures.FAKE_10K_HTML, fixtures.FAKE_FACTS, ":memory:")
    print(f"解析完成：{len(sections)} 个 Item / {len(chunks)} 个段落 / {len(tables)} 张表 "
          f"/ {conn.execute('SELECT COUNT(*) FROM facts').fetchone()[0]} 条 XBRL 事实\n")
    print("章节：" + "、".join(f"Item {s.item} {s.title}" for s in sections))
    ans = Answerer(chunks, conn)
    for q in SAMPLE_QUESTIONS:
        print(f"\n{'='*70}\nQ: {q}")
        print(ans.ask(q).render())
    print(f"\n{'='*70}\n表格（Item 8）：")
    for t in tables:
        print(" | ".join(t.header))
        for row in t.rows:
            print(" | ".join(row))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="filinglens", description="用自然语言查 SEC 公开文件，答案带出处")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("index", help="解析并建立索引")
    i.add_argument("--html", required=True)
    i.add_argument("--facts", default="")
    i.add_argument("--db", default="filinglens.db")
    i.set_defaults(func=cmd_index)

    a = sub.add_parser("ask", help="提问（可多个）")
    a.add_argument("questions", nargs="+")
    a.add_argument("--html", default="")
    a.add_argument("--facts", default="")
    a.add_argument("--with-fixture-facts", action="store_true")
    a.add_argument("--db", default=":memory:")
    a.add_argument("--json", action="store_true", help="输出 JSON（单问一条，多问包 answers）")
    a.set_defaults(func=cmd_ask)

    m = sub.add_parser("metric", help="取年度指标序列与同比")
    m.add_argument("metric", help="revenue / net_income / 研发 ...")
    m.add_argument("--facts", required=True)
    m.add_argument("--db", default=":memory:")
    m.set_defaults(func=cmd_metric)

    d = sub.add_parser("demo", help="零配置演示（内置夹具）")
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
