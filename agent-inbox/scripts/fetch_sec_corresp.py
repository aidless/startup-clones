"""下载某家公司的 SEC 往来函件（CORRESP / UPLOAD）。

这些是真实的企业与监管往来：有编号意见、有截止日期、有保密请求。
CORRESP = 公司回复；UPLOAD = 补充材料。SEC 的员工意见函单独存在于 0000000000 下，
所以本地语料常常「只有回复、没有来函」——脚本会把这一点如实报出来。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = "agent-inbox-research/0.1 (contact: research@example.com)"
DATA = Path(__file__).resolve().parents[1] / "data"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cik = int(sys.argv[1])
    DATA.mkdir(exist_ok=True)
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    recent = sub["filings"]["recent"]
    rows = [(recent["form"][i], recent["filingDate"][i],
             recent["accessionNumber"][i])
            for i in range(len(recent["form"]))
            if recent["form"][i] in ("CORRESP", "UPLOAD")]
    print(f"{sub.get('name')}: {len(rows)} 封往来函件")
    saved = 0
    for form, date, acc in rows[:8]:
        acc_nd = acc.replace("-", "")
        try:
            index = json.loads(get(
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/index.json"))
        except Exception as e:                       # noqa: BLE001
            print(f"  [跳过] {acc}: {e}")
            continue
        docs = [i["name"] for i in index["directory"]["item"]
                if i["name"].endswith((".htm", ".txt")) and not i["name"].endswith("-index.html")]
        primary = next((d for d in docs if d != f"{acc_nd}.txt"), None)
        if not primary:
            print(f"  [跳过] {acc}: 无比对文件")
            continue
        raw = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{primary}")
        out = DATA / f"{slug(acc)}_{form.lower()}.{primary.rsplit('.', 1)[-1]}"
        out.write_bytes(raw)
        print(f"  {date} {form:<8} {acc} → {out.name} ({len(raw)//1024} KB)")
        saved += 1
        time.sleep(1.2)                              # SEC 限速 10 req/s，保守一点
    print(f"保存 {saved} 个文件到 {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
