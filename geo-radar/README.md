# geo-radar

**AI 搜索引擎可见性监测** —— 看你的品牌在 ChatGPT / Perplexity / Gemini / AI Overview 的回答里被提到几次、排第几、被谁抢走了提及。

> 对标：The Prompting Company（2026-11 种子轮 $6.5M）。SEO 时代有 rank tracker，GEO 时代也得有。差别在于：LLM 的回答是分布不是排名，所以样本量和口径比什么都重要。

## 为什么这件事值得做

- 买家正在把「调研」搬到对话框里，官网流量在掉，但品牌方没有任何仪表盘。
- 全部输入都是公开的：提示词、模型输出、引用 URL。没有专有数据壁垒。
- 交付物是**动作**而不是图表：「去拿下引用占比 23% 的那个评测站」。

## 指标口径（写死，不许漂）

| 指标 | 定义 | 分母 |
| --- | --- | --- |
| 提及次数 | 回答正文中品牌名（词边界匹配）首次出现的次数 | — |
| 出现率 | 提到该品牌的提示词条数 | 提示词总条数 |
| 声量份额 SoV | 该品牌提及数 | 全部品牌提及数 |
| 平均位次 | 被提及时的平均出现次序（1 = 第一个被提到） | 该品牌被提及次数 |
| 引用份额 | 某域名被引用的次数 | 全部引用次数 |

**单次调用不可信**：同一提示词跑 3–5 次取分布，否则你测的是采样噪声。

## 快速开始

```bash
cd geo-radar
pip install -e .            # 或直接用 PYTHONPATH=.

# 零配置演示（内置确定性 MockProvider，不需要 API key）
python -m georadar.cli demo

# 真实模型
export GEO_API_KEY=sk-xxx
export GEO_BASE_URL=https://api.deepseek.com/v1   # 任何 OpenAI 兼容端点
python -m georadar.cli run \
  --brand Acme --category "AI SRE" \
  --competitors "Traversal,Rootly" \
  --provider openai --model deepseek-chat \
  --repeat 5 --out reports/acme.md
```

## 架构

```
prompts.py    提示词集生成（模板 × 受众 × 问题；绝不包含目标品牌名）
providers.py  LLM 适配（MockProvider 确定性 / OpenAI 兼容端点）
extract.py    提及抽取、位次、情感（纯规则，可回归，不随模型漂移）
metrics.py    SoV / 出现率 / 位次分布 / 引用源 / 差距
store.py      SQLite：run → answers（全文留档）→ mentions
report.py     Markdown 周报 + HTML
cli.py        run / report / demo
```

## 三条设计铁律

1. **提示词里不能出现目标品牌**。出现即污染，模型会顺着你的词夸。
2. **抽取逻辑不许用 LLM**。抽取一用模型，指标就不可回归，客户问「为什么上周 12% 这周 9%」你答不出来。
3. **原始回答必须落库**。GEO 的争议全在「你凭什么说我没被提到」，没有原文就无法自证。

## 路线图

- [x] 提示词集 / 多 provider / 抽取 / 指标 / 报表 / SQLite
- [ ] 竞品自动发现（从回答里反推同品类品牌）
- [ ] 引用源 → 可执行投放清单（哪个站点、投什么形态）
- [ ] 多语言 / 多地区（同一提示词在 zh-CN 与 en-US 的差异）
- [ ] 历史趋势与告警（SoV 环比掉 20% 发 Slack）

## 已知局限

- MockProvider 只用于测试与 demo，它的"品牌排序"是哈希产生的，没有语义。
- 情感用词典法，对否定句（"not the best"）会判错。生产环境需换成小模型分类器，但要保留可回归的标注集。

MIT License.
