#!/usr/bin/env python3
"""在 20 家真实公司的 10-K 上跑一遍，统计拒答率与错误率。

这是这个项目唯一能换成"信任"的数字——不是"我在 Apple 的一份文件上答对了 8 个问题"，
而是"在 20 家公司、20 份真实申报上，数字题答对多少、该拒答的拒掉多少、哪里错了"。

三类题，三种判法（判法必须可自动执行，否则统计就是自我感觉）：

1. **数字题**：真值来自 XBRL 本身，不来自我的答案。答案文本里的金额解析出来，
   与 XBRL 年度序列的最后一年比相对误差。XBRL 里没有这个指标（比如银行没有 R&D）
   记 `n/a` 并**从分母里剔除**——不能把"公司没披露"算成"系统答错"。
2. **文本题**：只验"给了答案且带段落级出处"。文本内容对不对机器判不了，
   硬判会得出假准确率，所以这一栏明确只报格式合规率。
3. **拒答题**：必须 `insufficient_evidence`。这类问题看起来像能答（"CEO 生日"），
   放过一条就意味着整个"没有引用就没有答案"的契约是假的。

用法：
    python3 scripts/batch_bench.py                 # 默认 20 家，缺的文件自动下载
    python3 scripts/batch_bench.py --limit 5
    python3 scripts/batch_bench.py --no-fetch      # 只用 data/ 里已有的
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens import corpus, facts as F, ingest  # noqa: E402
from filinglens.answer import headcount_number  # noqa: E402  —— 判据只能有一份

DATA = ROOT / "data"
OUT = ROOT / "bench"

# 20 家：科技 + 半导体 + 零售消费 + 银行 + 制药 + 工业。名字不硬编码，
# 输出里的公司名一律从 SEC 的 submissions 里读——避免张冠李戴。
COMPANIES = [
    "320193",   # Apple
    "789019",   # Microsoft
    "1652044",  # Alphabet
    "1018724",  # Amazon
    "1045810",  # NVIDIA
    "1326801",  # Meta
    "1318605",  # Tesla
    "1730168",  # Broadcom
    "1341439",  # Oracle
    "1108524",  # Salesforce
    "796343",   # Adobe
    "858877",   # Cisco
    "50863",    # Intel
    "2488",     # AMD
    "804328",   # Qualcomm
    "97476",    # Texas Instruments
    "80424",    # Procter & Gamble（不是 PepsiCo，PEP 是 77476——写错注释等于写错文档）
    "21344",    # Coca-Cola
    "104169",   # Walmart
    "19617",    # JPMorgan Chase
]

NUMERIC_QS = [
    ("revenue", "营收多少？"),
    ("net_income", "净利润多少？"),
    ("r_and_d", "研发费用多少？"),
]
TEXTUAL_QS = ["主要风险因素有哪些？"]
HEADCOUNT_Q = "有多少员工？"
REFUSAL_QS = ["CEO 的生日是哪天？", "公司有几家门店？"]

# 符号必须捕获：净利润 -267.0M 少了负号会被判成 267M，与真值差 200%，
# 于是基准把一条正确的答案记成错误——是尺子错了，不是产品错了。
AMOUNT_RE = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*([BMK])\s*USD")
SCALE = {"B": 1e9, "M": 1e6, "K": 1e3}


def parse_amount(text: str) -> float | None:
    m = AMOUNT_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", "")) * SCALE[m.group(2)]


def truth(conn, metric: str) -> tuple[int, float] | None:
    series = F.annual_series(conn, metric)
    if not series:
        return None
    last = series[-1]
    return last.fy, float(last.val)


def run_one(tag: str) -> dict:
    filing = corpus.load(DATA, tag)
    row = {"tag": tag, **{k: v for k, v in filing.meta().items() if k in
                          ("doc", "period", "sections", "chunks", "has_xbrl")}, "cases": []}

    for metric, q in NUMERIC_QS:
        resp = filing.answerer.ask(q)
        case = {"kind": "numeric", "metric": metric, "q": q, "response": resp}
        gt = truth(filing.conn, metric) if filing.conn else None
        if gt is None:
            case.update(verdict="n/a", truth=None)
        else:
            fy, val = gt
            got = parse_amount(resp.text) if resp.status == "ok" else None
            if got is None:
                case.update(verdict="wrong", truth=val, fy=fy, note="没有给出可解析的金额")
            else:
                rel = abs(got - val) / max(abs(val), 1.0)
                case.update(verdict="correct" if rel <= 0.005 else "wrong",
                            truth=val, got=got, rel=round(rel, 6), fy=fy)
        row["cases"].append(case)

    for q in TEXTUAL_QS:
        resp = filing.answerer.ask(q)
        ok = resp.status == "ok" and bool(resp.citations)
        row["cases"].append({"kind": "textual", "q": q, "verdict": "cited" if ok else "no_citation",
                             "response": resp, "confidence": round(resp.confidence, 3)})

    resp = filing.answerer.ask(HEADCOUNT_Q)
    # 判据直接复用产品里的那个函数：基准自己抄一份正则，抄的那一刻就开始测别的东西了
    num = headcount_number(resp.text) if resp.status == "ok" else None
    if resp.status != "ok":
        hc = "refused"
    else:
        hc = "numbered" if num else "wrong"     # 答了但没人数的，算错，不算"有答案"
    row["cases"].append({"kind": "headcount", "q": HEADCOUNT_Q, "verdict": hc,
                         "response": resp, "confidence": round(resp.confidence, 3),
                         "number": num})

    for q in REFUSAL_QS:
        resp = filing.answerer.ask(q)
        good = resp.status == "insufficient_evidence" and not resp.citations
        row["cases"].append({"kind": "refusal", "q": q,
                             "verdict": "refused" if good else "answered",
                             "response": resp, "confidence": round(resp.confidence, 3)})
    return row


def tally(rows: list[dict]) -> dict:
    num = [c for r in rows for c in r["cases"] if c["kind"] == "numeric" and c["verdict"] != "n/a"]
    txt = [c for r in rows for c in r["cases"] if c["kind"] == "textual"]
    ref = [c for r in rows for c in r["cases"] if c["kind"] == "refusal"]
    hc = [c for r in rows for c in r["cases"] if c["kind"] == "headcount"]
    na = [(r["tag"], c["metric"]) for r in rows for c in r["cases"]
          if c["kind"] == "numeric" and c["verdict"] == "n/a"]
    return {
        "companies": len(rows),
        "numeric_asked": len(num),
        "numeric_correct": sum(c["verdict"] == "correct" for c in num),
        "numeric_na": len(na),
        "na_list": na,
        "textual_asked": len(txt),
        "textual_cited": sum(c["verdict"] == "cited" for c in txt),
        "refusal_asked": len(ref),
        "refusal_refused": sum(c["verdict"] == "refused" for c in ref),
        "headcount_asked": len(hc),
        "headcount_numbered": sum(c["verdict"] == "numbered" for c in hc),
        "headcount_refused": sum(c["verdict"] == "refused" for c in hc),
        "headcount_wrong": sum(c["verdict"] == "wrong" for c in hc),
    }


def markdown(rows: list[dict], t: dict) -> str:
    acc = t["numeric_correct"] / t["numeric_asked"] * 100 if t["numeric_asked"] else 0
    cite = t["textual_cited"] / t["textual_asked"] * 100 if t["textual_asked"] else 0
    refuse = t["refusal_refused"] / t["refusal_asked"] * 100 if t["refusal_asked"] else 0
    lines = [
        "# 20 家真实 10-K 的基准结果", "",
        f"- 公司数：{t['companies']}（每家一份最新 10-K + companyfacts）",
        f"- 数字题：**{t['numeric_correct']}/{t['numeric_asked']} 正确（{acc:.1f}%）**，"
        f"另有 {t['numeric_na']} 题因 XBRL 未披露该项目记为 n/a（不计入分母）",
        f"- 文本题：**{t['textual_cited']}/{t['textual_asked']} 给出答案且带段落级出处（{cite:.1f}%）**"
        "（只验格式，内容对错机器判不了）",
        f"- 拒答题：**{t['refusal_refused']}/{t['refusal_asked']} 正确拒答（{refuse:.1f}%）**",
        f"- 员工数：**{t['headcount_numbered']}/{t['headcount_asked']} 给出人数**，"
        f"{t['headcount_refused']} 家明确拒答（文件里没有「N 名员工」这种陈述），"
        f"{t['headcount_wrong']} 家答了但没人数（应为 0）", "",
        "## 逐家", "",
        "| tag | 期间 | 章节 | 文本段 | 数字题 | 风险因素 | 员工数 | 拒答 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        num = [c for c in r["cases"] if c["kind"] == "numeric"]
        answered = [c for c in num if c["verdict"] != "n/a"]
        num_s = f"{sum(c['verdict'] == 'correct' for c in answered)}/{len(answered)}"
        na = len(num) - len(answered)
        if na:
            num_s += f" (n/a {na})"
        txt_s = f"{sum(c['verdict'] == 'cited' for c in r['cases'] if c['kind'] == 'textual')}/1"
        ref_s = f"{sum(c['verdict'] == 'refused' for c in r['cases'] if c['kind'] == 'refusal')}/2"
        hcc = next(c for c in r["cases"] if c["kind"] == "headcount")
        hc_s = {"numbered": "人数✓", "refused": "拒答", "wrong": "没人≠"}[hcc["verdict"]]
        lines.append(f"| {r['tag']} | {r['period']} | {r['sections']} | {r['chunks']} | "
                     f"{num_s} | {txt_s} | {hc_s} | {ref_s} |")

    bad = [(r["tag"], c) for r in rows for c in r["cases"]
           if c["kind"] == "numeric" and c["verdict"] == "wrong"]
    leaked = [(r["tag"], c) for r in rows for c in r["cases"]
              if c["kind"] == "refusal" and c["verdict"] == "answered"]
    if bad or leaked:
        lines += ["", "## 失败明细", ""]
        for tag, c in bad:
            lines.append(f"- `{tag}` {c['metric']}：答案 `{c['response'].text[:90]}` / "
                         f"XBRL FY{c.get('fy')} = {c.get('truth')}")
        for tag, c in leaked:
            lines.append(f"- `{tag}` 该拒答却答了：`{c['q']}` → `{c['response'].text[:90]}` "
                         f"（{c['confidence']}）")
    if t["na_list"]:
        lines += ["", "## XBRL 未披露（记为 n/a，不算错）", ""]
        lines.append("、".join(f"`{tag}:{m}`" for tag, m in t["na_list"]))
    lines += ["", "## 口径说明", "",
              "- 真值来自 XBRL companyfacts，不来自答案文本；相对误差 ≤0.5% 记为正确。",
              "- 「风险因素」只验「有答案 + 有出处」，不做语义判分。",
              "- 员工数必须给出「N 名员工」的陈述；只肯说「80% 员工是技术岗」不算答出人数。",
              "- 拒答题要求 `status=insufficient_evidence` 且 citations 为空。", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(COMPANIES))
    ap.add_argument("--no-fetch", action="store_true", help="只用 data/ 里已有的文件")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    rows: list[dict] = []
    for i, cik in enumerate(COMPANIES[: args.limit], 1):
        tag = f"{int(cik):010d}"
        if not (DATA / f"{tag}_facts.json").exists() and not args.no_fetch:
            try:
                info = ingest.from_cik(cik, DATA)
                print(f"[{i}/{args.limit}] 下载 {tag} {info.get('company', '')} "
                      f"{info['html_kb']}KB", flush=True)
            except Exception as exc:                       # noqa: BLE001
                print(f"[{i}/{args.limit}] {tag} 下载失败：{exc}", flush=True)
                continue
        try:
            row = run_one(tag)
        except Exception:                                  # noqa: BLE001
            print(f"[{i}/{args.limit}] {tag} 解析失败：\n{traceback.format_exc()}", flush=True)
            continue
        rows.append(row)
        num = [c for c in row["cases"] if c["kind"] == "numeric" and c["verdict"] != "n/a"]
        print(f"[{i}/{args.limit}] {tag} {row['period']} 章节{row['sections']} "
              f"数字 {sum(c['verdict'] == 'correct' for c in num)}/{len(num)}", flush=True)

    t = tally(rows)
    (OUT / "report.json").write_text(json.dumps({"tally": t, "rows": [
        {**{k: v for k, v in r.items() if k != "cases"},
         "cases": [{**{k: v for k, v in c.items() if k != "response"},
                    "text": c["response"].text} for c in r["cases"]]} for r in rows]},
        ensure_ascii=False, indent=2))
    md = markdown(rows, t)
    (OUT / "report.md").write_text(md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
