#!/usr/bin/env python3
"""语料矩阵：把 `filing-lens/data/` 里每一份 10-K 都真解析一遍，逐份出读数。

为什么需要它：`filing-lens` 的 103 个测试全是**夹具**（`fixtures.py` 里那几段 HTML），
它们证明规则按设计生效，但证明不了「真实世界里那 22 份文件都能解析」。端到端
串联（`scripts/e2e.py`）也只固定了 Apple 一份——其余 21 份的解析差异没有任何
一处会跑它。

本脚本对每份文件输出一行读数（章节数 / 段落数 / 表格数 / 是否有 XBRL /
一个数字题的回答状态），并在末尾给出汇总。它**不判定「答案对不对」**——
那要人工看；它判定的是「有没有哪份文件根本读不通」。

用法：
    python3 scripts/corpus_matrix.py                 # 人读表格
    python3 scripts/corpus_matrix.py --json          # 结构化（给测试与 CI 用）
    python3 scripts/corpus_matrix.py --ask           # 额外跑一个数字题（慢，约 2 倍）
    python3 scripts/corpus_matrix.py --only 0000320193            # 只跑一份（测试用）
    python3 scripts/corpus_matrix.py --baseline docs/corpus-matrix.json   # 与基线比对
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILING_DIR = ROOT / "filing-lens"
DATA_DIR = FILING_DIR / "data"
QUESTION = "What was net income?"


def _rows(ask: bool, only: set[str] | None = None) -> list[dict]:
    sys.path.insert(0, str(FILING_DIR))
    from filinglens.corpus import Filing               # noqa: E402
    from filinglens.corpus import discover             # noqa: E402

    rows = []
    for entry in discover(DATA_DIR):
        cik, period = entry["cik"], entry["period"]
        if only and cik not in only:
            continue
        html = DATA_DIR / f"{cik}_10k_{period}.htm"
        facts = DATA_DIR / f"{cik}_facts.json"
        row: dict = {"cik": cik, "period": period,
                     "facts": facts.exists(), "ok": False, "error": ""}
        started = time.perf_counter()
        try:
            f = Filing(cik, html, facts if facts.exists() else None)
            row.update(f.meta())
            row["ok"] = True
            if ask:
                ans = f.answerer.ask(QUESTION)
                row["answer"] = {
                    "status": ans.status,
                    "confidence": round(ans.confidence, 3),
                    "citations": len(ans.refs or []),
                }
        except Exception as exc:                      # noqa: BLE001 —— 这一行就是要抓住"哪份读不通"
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        row["ms"] = round((time.perf_counter() - started) * 1000)
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="corpus_matrix", description="全语料解析矩阵")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--ask", action="store_true", help="额外跑一个数字题")
    ap.add_argument("--only", default="", help="逗号分隔的 CIK，只跑这几份")
    ap.add_argument("--baseline", default="", help="与已记录的矩阵 JSON 比对（漂移即 exit 1）")
    args = ap.parse_args(argv)

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    rows = _rows(args.ask, only)
    broken = [r for r in rows if not r["ok"]]
    summary = {
        "total": len(rows),
        "ok": len(rows) - len(broken),
        "broken": len(broken),
        "with_facts": sum(1 for r in rows if r["facts"]),
        "min_chunks": min((r.get("chunks", 0) for r in rows), default=0),
        "min_sections": min((r.get("sections", 0) for r in rows), default=0),
    }
    if args.json:
        print(json.dumps({"rows": rows, "summary": summary},
                         ensure_ascii=False, indent=2))
        return 1 if broken else 0

    print(f"{'CIK':<12} {'期间':<12} {'章节':>4} {'段落':>6} {'表格':>4} {'XBRL':>5} {'ms':>6}  备注")
    for r in rows:
        note = r["error"] or ("" if r["ok"] else "未解析")
        if r.get("answer"):
            note = f"{r['answer']['status']} conf={r['answer']['confidence']} refs={r['answer']['citations']}"
        print(f"{r['cik']:<12} {r['period']:<12} {r.get('sections', 0):>4} "
              f"{r.get('chunks', 0):>6} {r.get('tables', 0):>4} "
              f"{('有' if r.get('has_xbrl') else '无'):>5} {r['ms']:>6}  {note}")
    drift = _compare_baseline(rows, args.baseline) if args.baseline else []
    if drift:
        print("\n与基线不一致：")
        for line in drift:
            print(f"  - {line}")
    print(f"\n矩阵：{summary['ok']}/{summary['total']} 份解析成功"
          f"（其中有 XBRL {summary['with_facts']} 份）；最少章节 {summary['min_sections']}、"
          f"最少段落 {summary['min_chunks']}")
    return 1 if broken or drift else 0


def _compare_baseline(rows: list[dict], path: str) -> list[str]:
    """与记录的基线逐份比对**结构读数**（不含耗时与回答）。"""
    recorded = json.loads(Path(path).read_text(encoding="utf-8"))
    base = {r["cik"]: r for r in recorded["rows"]}
    fields = ("ok", "sections", "chunks", "tables", "facts")
    drift = []
    for r in rows:
        old = base.get(r["cik"])
        if old is None:
            drift.append(f"{r['cik']}：基线里没有这份文件")
            continue
        for f in fields:
            if old.get(f) != r.get(f):
                drift.append(f"{r['cik']} 的 {f}：基线 {old.get(f)} → 现在 {r.get(f)}")
    for cik in base:
        if cik not in {r["cik"] for r in rows}:
            drift.append(f"{cik}：基线里有，这次没跑")
    return drift


if __name__ == "__main__":
    raise SystemExit(main())
