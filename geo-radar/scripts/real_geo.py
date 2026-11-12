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
from georadar.providers import build_provider  # noqa: E402

CATEGORIES: dict[str, dict] = {
    "expense": {
        "brands": ["Ramp", "Brex", "Mercury", "Expensify", "Bill.com", "Navan",
                   "Divvy", "Airbase", "Stampli", "Coupa"],
        "prompts": [
            "What is the best expense management software for a 50-person startup?",
            "Which corporate card should a seed-stage startup use?",
            "Compare Ramp and Brex for startups.",
            "What tools automate expense reports for a small finance team?",
            "Which software do CFOs use to track startup spend?",
            "Which spend management platform has the best accounting integration?",
            "What is the best alternative to Expensify for a US startup?",
            "Which vendor and spend tools should a Series A company evaluate?",
        ],
    },
    "crm": {
        "brands": ["Salesforce", "HubSpot", "Pipedrive", "Close", "Attio", "Zoho",
                   "Copper", "Folk", "Monday", "Freshsales"],
        "prompts": [
            "What is the best CRM for a 20-person B2B startup?",
            "Which CRM should a solo founder use?",
            "Compare HubSpot and Pipedrive for a small sales team.",
            "What CRM has the best email integration?",
            "Which CRM is easiest to set up without an admin?",
            "Best lightweight alternative to Salesforce for startups?",
            "Which CRM do seed-stage startups actually use?",
            "What CRM should a Series A sales team migrate to?",
        ],
    },
    "support": {
        "brands": ["Zendesk", "Intercom", "Freshdesk", "Help Scout", "Front", "Crisp",
                   "Gorgias", "Kustomer", "Kayako", "LiveAgent"],
        "prompts": [
            "What is the best customer support tool for a small SaaS company?",
            "Which helpdesk should a 5-person support team use?",
            "Compare Zendesk and Intercom for a startup.",
            "What support tool has the best AI auto-reply?",
            "Which shared inbox tool is best for a small team?",
            "Best alternative to Zendesk for a bootstrapped company?",
            "Which support platform integrates best with Shopify?",
            "What tool should a Series A company use for customer support?",
        ],
    },
}

LOCAL_MODELS = ["llama3.2:3b", "qwen2.5:7b", "qwen3:8b"]
# Magpie 网关上的免费/低价模型（本机 127.0.0.1:3425）：
# deepseek-v4.1-flash 与 hy4free、ernie-5.5-flash-preview:free 是 0 价；
# deepseek-v4.1-flash-max / gpt-6.1-terra 是低价档，用来做「强模型」对照。
MAGPIE_MODELS = ["deepseek-v4.1-flash", "hy4free",
                 "openrouter/baidu/ernie-5.5-flash-preview:free",
                 "deepseek-v4.1-flash-max", "gpt-6.1-terra"]


def main() -> int:
    argv = sys.argv[1:]
    limit = 0  # 0 = 该赛道全部提示词
    kind = "ollama"
    models = LOCAL_MODELS
    for a in argv:
        if a.startswith("--provider="):
            kind = a.split("=", 1)[1]
        elif a.startswith("--models="):
            models = a.split("=", 1)[1].split(",")
        elif a.isdigit():
            limit = int(a)
    category = "expense"
    for a in argv:
        if a.startswith("--category="):
            category = a.split("=", 1)[1]
    if category not in CATEGORIES:
        raise SystemExit(f"未知赛道 {category}，可选 {sorted(CATEGORIES)}")
    brands = CATEGORIES[category]["brands"]
    all_prompts = CATEGORIES[category]["prompts"]
    prompts = all_prompts[:limit] if limit else all_prompts
    provider = build_provider(kind, brands)
    print(f"category={category} provider={kind} models={models}", flush=True)
    out = ROOT / f"data/geo_real_{category}_{kind}.json"
    # 支持分批跑：已跑过的模型结果保留，重跑只覆盖同名模型
    result: dict = {"category": category, "brands": brands,
                    "prompts": prompts, "models": {}}
    if out.exists():
        try:
            prev = json.loads(out.read_text())
            if prev.get("brands") == brands:
                result["models"] = prev.get("models", {})
                print(f"接续已有结果：{sorted(result['models'])}", flush=True)
        except json.JSONDecodeError:
            pass

    for model in models:
        print(f"\n=== {model} ({len(prompts)} 条提示词) ===", flush=True)
        mentions = []
        answers = []
        for i, p in enumerate(prompts, 1):
            try:
                ans = provider.complete(p, model=model)
            except Exception as exc:  # 单条失败不能毁掉整轮
                print(f"  [{i}] 失败: {exc}", flush=True)
                continue
            found = find_mentions(ans, brands)
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
