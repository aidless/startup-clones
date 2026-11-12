"""在真实的 MCP server 清单上跑入市审查，输出结论表。

回答的问题只有一个：**真实的 agent 商店清单里，权限声明存在吗？**
如果答案是「几乎不存在」，那么「商店」的价值就不在托管、不在计费，
而在替买家把这份没写的东西补出来。
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentstore.intake import load_dir, review  # noqa: E402


def main() -> int:
    raws = load_dir(str(ROOT / "data/raw"))
    if not raws:
        print("没有清单，先跑 scripts/fetch_mcp_servers.py")
        return 1
    rows = [review(r) for r in raws]

    print(f"{'仓库':<44}{'版本':>9}  {'推断权限':<34}{'声明':>4}  {'最严'}")
    for r in rows:
        print(f"{r['repo']:<44}{r['version']:>9}  {','.join(r['inferred']) or '-':<34}"
              f"{len(r['declared']):>4}  {r['worst']}")

    n = len(rows)
    with_decl = sum(1 for r in rows if r["declared"])
    worst = collections.Counter(r["worst"] for r in rows)
    rule_count = collections.Counter(f["rule"] for r in rows for f in r["findings"])
    secret = sum(1 for r in rows if "secrets.read" in r["inferred"])
    write = sum(1 for r in rows if "fs.write" in r["inferred"])
    pay = sum(1 for r in rows if "payment.charge" in r["inferred"])
    pinned = sum(1 for r in rows if r["version"] not in ("-", "0.0.0"))

    print(f"\n清单 {n} 份 | 声明了权限 {with_decl} 份 | 版本可固定 {pinned} 份")
    print(f"推断需要：密钥 {secret} / 写文件 {write} / 动钱 {pay}")
    print(f"最严等级分布：{dict(worst)}")
    print("规则命中：")
    for rule, c in rule_count.most_common():
        print(f"  {rule:<36}{c:>3} 份")

    out = ROOT / "data/review.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"\n明细写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
