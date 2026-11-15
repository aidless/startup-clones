"""六项检查在真实语料上的「有没有在测」普查。

为什么需要它：每项检查有三种结局——报 mismatch（抓到）、报 look/info（看过了给事实）、
skipped（没拿到东西）。只数 mismatch 会把「silent」和「干净」混成一个读数：
两者在报表上都长得像「没有发现问题」。这个脚本把三项分开数，silent 的检查必须
在报表里被点出来，否则它只是装饰（AGENTS.md 第 37 条：门要能红，也要先证明它不是空转）。

用法：
    python3 scripts/check_coverage.py            # 人读表
    python3 scripts/check_coverage.py --json     # 机器读
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from filinglens import corpus  # noqa: E402
import review_diff as rd  # noqa: E402
# 检查名带括号后缀（「正文百分比（营业收入）」），按前缀归到六项固定项上。
# 只认前缀是刻意的：新加子项不必改这张表，但也因此不能靠名字「凑齐」，凑齐要看
# 每个前缀下到底有没有一条真命中。
CHECKS = (
    "现金流量口径",
    "员工数",
    "同比口径",
    "分部加总",
    "正文百分比",
    "正文与 XBRL",
    "风险因素年度差异",
)
# 语料里必然一次都命中不了的检查，以及为什么 —— 写清楚比让它静默强。
KNOWN_SILENT = {
    "风险因素年度差异": "每个 CIK 在 data/ 里只有一份 10-K，没有上年可比（22/22 skipped）",
}


def canon(name: str) -> str:
    for c in CHECKS:
        if name.startswith(c):
            return c
    return name


def survey(data_dir: Path) -> dict:
    rows = []
    tally = OrderedDict((c, {"mismatch": 0, "look": 0, "info": 0, "skipped": 0}) for c in CHECKS)
    sub = OrderedDict()
    for meta in sorted(corpus.discover(data_dir), key=lambda m: m["cik"]):
        rep = rd.build(meta["cik"], data_dir)
        for x in rep.findings:
            key = canon(x.check)
            tally[key][x.severity if x.severity in ("mismatch", "look", "info") else "info"] += 1
            sub.setdefault(x.check, 0)
            sub[x.check] += 1
        for name, _why in rep.skipped:
            # 未登记的名字（检查名换过、或新加子项）不许静默消失：建一行再计数。
            tally.setdefault(canon(name), {"mismatch": 0, "look": 0, "info": 0, "skipped": 0})
            tally[canon(name)]["skipped"] += 1
            sub.setdefault(name, 0)
        rows.append({
            "cik": meta["cik"], "entity": rep.entity or meta.get("tag", ""),
            "findings": len(rep.findings), "skipped": len(rep.skipped),
            "by_check": {k: sum(1 for x in rep.findings if x.check == k) for k in CHECKS},
        })
    # 空转 = 从没出现过（既没命中也没 skip）。只在 skipped 里出现是「没有数据」，
    # 与「跑了但从不说话」是两件事：前者是语料的性质，后者是检查的性质。
    silent = [c for c, n in tally.items()
              if n["mismatch"] + n["look"] + n["info"] + n["skipped"] == 0
              and c not in KNOWN_SILENT]
    unexplained = [c for c in silent]
    return {"rows": rows, "tally": tally, "silent": silent,
            "known_silent": KNOWN_SILENT, "unexplained": unexplained,
            "sub_items": sub, "files": len(rows), "findings": sum(r["findings"] for r in rows)}


def render(res: dict) -> str:
    lines = [f"# 六项检查的覆盖普查（{res['files']} 份 10-K）", "",
             f"合计命中 {res['findings']} 条。`skipped` 是「这一项没拿到东西」，不是「检查通过」。", "",
             "| 检查 | mismatch | look | info | skipped | 状态 |", "|---|---|---|---|---|---|"]
    for name, n in res["tally"].items():
        fired = n["mismatch"] + n["look"] + n["info"]
        if fired:
            state = "有 mismatch" if n["mismatch"] else "只给事实"
        elif name in res["known_silent"]:
            state = "已知不可用"
        elif n["skipped"]:
            state = "只在 skipped（<b>没有数据</b>）".replace("<b>", "").replace("</b>", "")
        else:
            state = "空转（从没出现过）"
        lines.append(f"| {name} | {n['mismatch']} | {n['look']} | {n['info']} | {n['skipped']} | {state} |")
    if res["known_silent"]:
        lines += ["", "## 已知不可用（有理由，不是 bug）"]
        lines += [f"- **{c}**：{why}" for c, why in res["known_silent"].items()]
    lines += ["", "## 空转项（必须有注入证明，否则等于没测）"]
    lines += [f"- **{c}**：{res['files']} 份语料里一次都没命中，也没有 skipped 记录"
              for c in res["silent"]] or ["- 无"]
    lines += ["", "## 逐份读数", "", "| CIK | 主体 | 命中 | 未覆盖 |", "|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| `{r['cik']}` | {r['entity']} | {r['findings']} | {r['skipped']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = survey(Path(a.data))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
