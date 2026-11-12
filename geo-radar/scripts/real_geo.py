"""在本机多个小模型上跑真实采样，回答一个产品问题：

**同一个买家问题，换个模型，推荐名单会不会变？**

会变，就说明单模型 GEO 报告是不可信的——这正是这个产品存在的理由。
不会变，就说明这份报告可以只跑一个模型，成本能砍掉 2/3。
两种结论都是产品决策依据，所以必须真跑。

用法：python3 scripts/real_geo.py [每模型提示词数]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from georadar.extract import find_mentions  # noqa: E402
from georadar.metrics import brand_stats  # noqa: E402
from georadar.providers import OllamaProvider  # noqa: E402

BRANDS = ["Ramp", "Brex", "Mercury", "Expensify", "Bill.com", "Navan",
          "Divvy", "Airbase", "Stampli", "Coupa"]

PROMPTS = [
    "What is the best expense management software for a 50-person startup?",
    "Which corporate card should a seed-stage startup use?",
    "Compare Ramp and Brex for startups.",
    "What tools automate expense reports for a small finance team?",
    "Which software do CFOs use to track startup spend?",
    "Which spend management platform has the best accounting integration?",
    "What is the best alternative to Expensify for a US startup?",
    "Which vendor and spend tools should a Series A company evaluate?",
]

MODELS = ["llama3.2:3b", "qwen2.5:7b", "qwen3:8b"]


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(PROMPTS)
    prompts = PROMPTS[:limit]
    provider = OllamaProvider()
    result: dict = {"brands": BRANDS, "prompts": prompts, "models": {}}

    for model in MODELS:
        print(f"\n=== {model} ({len(prompts)} 条提示词) ===", flush=True)
        mentions = []
        answers = []
        for i, p in enumerate(prompts, 1):
            try:
                ans = provider.complete(p, model=model)
            except Exception as exc:  # 单条失败不能毁掉整轮
                print(f"  [{i}] 失败: {exc}", flush=True)
                continue
            found = find_mentions(ans, BRANDS)
            mentions.extend(found)
            answers.append({"prompt": p, "text": ans.text[:1500],
                            "brands": [m.brand for m in found]})
            print(f"  [{i}] 提及 {[m.brand for m in found]}", flush=True)

        stats = brand_stats(mentions, len(prompts))
        table = sorted(
            ({"brand": b, "mentions": s.mentions, "share": round(s.share_of_voice, 3),
              "avg_position": round(s.avg_position, 2) if s.mentions else None}
             for b, s in stats.items()),
            key=lambda r: (-r["mentions"], r["avg_position"] or 99))
        result["models"][model] = {"table": table, "answers": answers}
        for row in table[:6]:
            print(f"    {row['brand']:<12}{row['mentions']:>3} 次  份额 {row['share']:.1%}  "
                  f"平均位次 {row['avg_position']}", flush=True)

    out = ROOT / "data/geo_real.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n写入 {out}")

    # 跨模型一致性：同一品牌的份额在各模型间差多少
    print("\n=== 跨模型一致性 ===")
    shares: dict[str, list[float]] = {}
    ranks: dict[str, list[int]] = {}
    for model, blob in result["models"].items():
        for row in blob["table"]:
            shares.setdefault(row["brand"], []).append(row["share"])
    for brand, vals in shares.items():
        if len(vals) >= 2:
            spread = max(vals) - min(vals)
            print(f"  {brand:<12}份额 {['%.1f%%' % (v * 100) for v in vals]}  极差 {spread:.1%}")
    _ = ranks
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
