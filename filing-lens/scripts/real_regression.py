#!/usr/bin/env python3
"""在真实 10-K 上跑一组问题，逐条对期望值。数据缺失时跳过（不联网）。

前置：python scripts/fetch_edgar.py 0000320193
用法：python scripts/real_regression.py
退出码：0 全过 / 1 有失败 / 0 + SKIP 提示（无数据）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens.answer import Answerer          # noqa: E402
from filinglens.edgar import parse              # noqa: E402
from filinglens.facts import load_companyfacts  # noqa: E402

EXPECT = json.loads((ROOT / "tests" / "golden_aapl_fy26.json").read_text())


def main() -> int:
    data = ROOT / "data"
    html_path = data / "0000320193_10k_2026-09-26.htm"
    facts_path = data / "0000320193_facts.json"
    if not (html_path.exists() and facts_path.exists()):
        print("SKIP：data/ 里没有 Apple 10-K。先跑 python scripts/fetch_edgar.py 0000320193")
        return 0

    _, chunks, tables = parse(html_path.read_text(errors="ignore"), doc="AAPL-FY26")
    conn = load_companyfacts(json.loads(facts_path.read_text()))
    answerer = Answerer(chunks, conn)
    print(f"chunks={len(chunks)} tables={len(tables)}\n")

    failed = 0
    for case in EXPECT:
        r = answerer.ask(case["q"])
        flat = " ".join(r.text.split())
        problems = []
        if r.status != case["status"]:
            problems.append(f"status {r.status} != {case['status']}")
        for s in case.get("contains", []):
            if s not in flat:
                problems.append(f"缺少 {s!r}")
        for s in case.get("not_contains", []):
            if s in flat:
                problems.append(f"不该出现 {s!r}")
        if case.get("cite_has") and not any(case["cite_has"] in c.ref for c in r.citations):
            problems.append(f"引用里没有 {case['cite_has']}")
        flag = "PASS" if not problems else "FAIL"
        if problems:
            failed += 1
        print(f"[{flag}] {case['q']}")
        print(f"       {flat[:150]}")
        for p in problems:
            print(f"       ✗ {p}")

    print(f"\n{len(EXPECT) - failed}/{len(EXPECT)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
