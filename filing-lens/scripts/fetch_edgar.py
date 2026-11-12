#!/usr/bin/env python3
"""从 SEC EDGAR 拉真实 10-K 与 XBRL companyfacts。

用法：
    python scripts/fetch_edgar.py 0000320193 0000789019 0000021344
数据落在 data/（已被 .gitignore 忽略），不提交到仓库：
SEC 要求声明 User-Agent，且不要高频抓取（每秒 1 次以内）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

UA = "filing-lens-research/0.1 (contact: research@example.com)"
DATA = Path(__file__).resolve().parent.parent / "data"


def get(url: str, retries: int = 3) -> bytes:
    for i in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 + i * 2)
    raise RuntimeError("unreachable")


def fetch_company(cik: str) -> None:
    cik10 = f"{int(cik):010d}"
    DATA.mkdir(exist_ok=True)

    subs = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    recent = subs["filings"]["recent"]
    rows = list(zip(recent["form"], recent["accessionNumber"], recent["primaryDocument"],
                    recent["filingDate"], recent["reportDate"]))
    tenk = [r for r in rows if r[0] == "10-K"][:1]
    if not tenk:
        print(f"{cik10}: 没有 10-K")
        return
    _, acc, doc, filed, period = tenk[0]
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}"
    html = get(url)
    out = DATA / f"{cik10}_10k_{period or filed}.htm"
    out.write_bytes(html)
    print(f"{cik10}: {subs['name']} 10-K {filed} → {out.name} ({len(html)/1024:.0f} KB)")

    facts = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
    (DATA / f"{cik10}_facts.json").write_bytes(facts)
    print(f"{cik10}: companyfacts {len(facts)/1024:.0f} KB")


if __name__ == "__main__":
    ciks = sys.argv[1:] or ["0000320193", "0000789019", "0000021344"]
    for c in ciks:
        fetch_company(c)
        time.sleep(1.2)   # SEC 限速：<=10 req/s，这里更保守
