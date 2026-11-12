"""在真实 SEC CORRESP 往来函件上跑结构化 + 线程重建。

    python scripts/fetch_sec_corresp.py 0000320193     # 拉 Apple 的往来函件
    python scripts/real_corresp.py                     # 解析 data/*.htm
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentinbox.corresp import build_threads, escalate, parse_letter  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "data").glob("*.htm"))
    if not files:
        print("data/ 里没有函件，先跑 scripts/fetch_sec_corresp.py")
        return 2
    letters = []
    for p in files:
        text = BeautifulSoup(p.read_text(errors="ignore"), "lxml").get_text("\n")
        try:
            letters.append(parse_letter(text, doc_id=p.stem))
        except ValueError as e:
            print(f"[跳过] {p.name}: {e}")
    threads, gaps = build_threads(letters)

    print(f"解析 {len(letters)} 封，{len(threads)} 个线程\n")
    for t in threads:
        print(f"线程 {t[0].thread_key}")
        for l in t:
            print("  ", l.render())
            print("      审批流:", " → ".join(escalate(l)))
    if gaps:
        print("\n缺口（产品必须显示，而不是假装接上了）：")
        for g in gaps:
            print("  ", g.doc_id, "|", g.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
