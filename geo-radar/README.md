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

## 已知边界

下面每一条都指到实现位置，说的是「什么情况下这份报告的结论不可信」，不是免责声明。

- **份额是「候选清单内份额」，不是市场份额。** 候选品牌只有 `--brand` + `--competitors`（`cli.py:21-22`），模型实际推荐的其它工具根本不进统计；声量份额的分子是该品牌的提及记录数、分母是全部候选品牌的提及记录数（`metrics.py:38`、`metrics.py:26-29`）—— 既不按回答计，也不按品牌数计。清单漏一个竞品，所有品牌的份额都会跟着变。
- **一次回答里同一品牌只算 1 次提及（口径选择，不是缺陷）。** `extract.find_mentions` 会把每个品牌的**全部**出现位置都扫出来，按 span 去重后取它最早那次有效出现（`extract.py:52-92`），所以「出现 5 次」与「出现 1 次」份额完全相同——它回答的是「这次回答提到它没有」；出现率的分母是提示词条数、分子是提到过该品牌的提示词条数（`metrics.py:50`、`metrics.py:57-61`）。
- **情感是 10 个褒义词 vs 10 个贬义词的词典差，判不了就给 0。** 词表在 `extract.py:11-12`，只统计该提及前 96 字、后 48 字窗口内的命中（`extract.py:28`、`extract.py:77-78`），算法是 `(pos-neg)/(pos+neg)`（`extract.py:44-50`）；窗口里一个情感词都没有时返回 `0.0`，与「真正中性」不可区分，也分不出「提到但没评价」。否定句会被判反：实测 `"this is not the best tool"` 返回 `+1.0`。
- **品牌匹配没有别名表。** 只按传入的字面名字做大小写不敏感的边界匹配（`extract.py:31-37`），中文译名、缩写、拼写变体（`Billcom`）一律算未提及。互为前缀的品牌在同一位置只保留最长的那个（`extract.py:74-88`），被更长的名字完全包住的那次出现不计；但品牌在别处独立出现时仍会被单独记一条——实测 `"Bill.com is fine. Bill Gates also uses it."` 抽出 2 条（`Bill.com` 第 1 位、`Bill` 第 2 位）。同名不同实体（Bill 人名 / Bill.com 公司）在非重叠位置仍然无法区分，这一点没有解。
- **份额是采样读数，不是确定性数字。** 真实模型每次回答都会变（MockProvider 也把 `run_index` 放进随机种子来模拟这一点，`providers.py:48-53`），报表只给点估计、不给区间（`report.py:48`、`report.py:56-66`）。样本量 = 提示词数 × 采样次数：8 条提示词时，多一条提及就把份额推 12.5 个百分点，位次和情感的抖动同理。
- **`run` 与 `report --run-id` 现在同口径（本次修好，旧库不自动迁移）。** 曾经的主键是 `(run_id, prompt_id, brand)`，同一 prompt 的多次采样被压成一条：内存 72 条 mention、落库只剩 32 条，Acme 的 SoV 34.72% → 34.38%、平均位次 1.52 → 1.27。现在主键带上 `run_index`（`store.py:43-52`），实测 12 × 3 两条路径都是 72 条、34.7%、1.52。**但**：这次修复之前生成的 `.db` 不会自动补 `run_index`，里面的 mentions 仍是压扁的，重跑是最省事的办法。
- **两条命令共用同一个装配函数（2026-11-14）。** `run` 落库后不再用内存里的 `stats` 渲染，而是 `store.load_run` → `view.assemble` 从库里读回来装配（`cli.py:45`）；`report --run-id` 走同一个 `view.load_view`（`cli.py:64`、`view.py:61`）。装配本身只有一份：`view.assemble`（`view.py:43`），分母写死为「answers 里真出现过的 prompt_id 条数」（`view.py:51`）——原先 `run` 用 `len(ps)`、`report` 用 `len(ids)`，只在每次采样都成功时碰巧相等。并列行（同提及数、同引用占比）现在按品牌名/域名兜底定序（`report.py:60`、`report.py:107`），否则内存顺序与 SQLite 的 `ORDER BY prompt_id,run_index` 顺序不同会让同一批数据印出不同行序（实测第 32 行 `zhihu.com` vs `forrester.com`）。markdown 里没有 run_id / created_at，所以两条路径的报表是**逐字节**相等（`tests/test_single_path.py`）；run 级元数据只存在 runs 表里。
- **「领先 / 落后」三个维度各判各的方向。** 差距句按三项分别措辞（`report.py:_gap_lines`）：
  声量用**百分点**（`gap_sov = 竞品 SoV − 我方 SoV`，为正=落后）、出现率用**条提示词**
  （为正=我们少出现）、平均位次用**位**（为正=我们名次更靠前，因为位次数字越小越好）。
  旧版按 `gap_sov` 一句话决定「领先/落后」再把另外两项取反照抄，于是印出
  「出现率多 **-1** 条提示词」「平均位次领先 **-0.8** 位」这种负数量的领先。
  「竞品」仍取 `--competitors` 里提及最多的那一个（`metrics.py:89`），不是全场第一——这点没变。
- **未被提及的品牌不出现在表里；零提及的 `avg_position` 是 `None`（原来返回 `0.0`）**（`metrics.py:31-34`、`metrics.py:90-104`）。
  位次数字越小越好，所以 `0.0` 会被下游读成「第一名」——旧版就是这么错的。现在报表里印 `—`，JSON 里是 `null`，
  差距句里若有一方零提及则写「平均位次无从比较」，不做 `None` 减法。
- MockProvider 的品牌顺序是哈希打散的（`providers.py:49-53`），只用来验证抽取/排名/份额链路，不能当语义结论；引用源是拿 URL 正则从**回答正文**里抓出来的（`providers.py:106-107`、`providers.py:26`），正文没写 URL 时第 4 节就是「无引用源」（`report.py:102-109`），模型在正文里不链源并不等于它没依据。

MIT License.

## 真实采样：3 个本机模型 × 8 个买家问题

`scripts/real_geo.py` 走本机 Ollama（不需要任何付费 key），对同一批买家问题
分别问 `llama3.2:3b` / `qwen2.5:7b` / `qwen3:8b`，抽取品牌并算份额。
标的物是费用管理赛道（Ramp / Brex / Mercury / Expensify / Bill.com / Navan / Divvy / Airbase / Stampli / Coupa）。

### 结论一：第一名稳，第二名是噪声

| 品牌 | llama3.2:3b | qwen2.5:7b | qwen3:8b | 极差 |
|---|---|---|---|---|
| Expensify | 54.5% | 55.6% | 50.0% | **5.6pt** |
| Coupa | 9.1% | 11.1% | 25.0% | 15.9pt |
| Brex | 9.1% | 22.2% | 12.5% | 13.1pt |
| Ramp | 9.1% | 11.1% | 12.5% | 3.4pt |
| Bill.com | 18.2% | — | — | 18.2pt |

三模型一致把 Expensify 放第一（50–56%），这个结论可以拿去卖。
**但从第二名开始，换模型就换人**：Bill.com 只在 3B 模型里出现，Coupa 在 8B 模型里翻倍。
任何一份「我们排第 3」的单模型报告，都是在卖噪声。

这条直接决定产品形态：报告必须标「名次置信带」，第 1 名之外的名次只报「是否进入前 N」，
不报精确位次；要报位次就得跑多次采样并给区间。

### 结论二：小模型的「召回率」本身就是偏差

8 个回答里，每个模型平均只点名 1–2 个品牌（总提及 11 条 / 3 模型 × 8 问）。
它们不是「认为只有这些」，而是「想不起来更多」。所以本地小模型测的是**认知度**，
不是**市场份额**——把这份数据当市场分额用，会系统性低估长尾玩家。

### 结论三：一次真跑才能发现的两个坑

| 现象 | 原因 | 修法 |
|---|---|---|
| qwen3:8b 八条全空，份额全 0 | 混合推理模型默认先吐 thinking，把 `num_predict` 吃光 | 请求体加 `think=false`；空返回抛错，不许当「没提到」 |
| `--provider ollama` 空答案 | 混合推理模型把 `num_predict` 吃光（**接线本身是好的**，`cli.py` 的 choices 里有 `ollama`） | 请求体加 `think=false`；`OLLAMA_HOST` 可覆盖默认 `127.0.0.1:11434` |

把「空答案」和「没提到该品牌」混为一谈，会让份额分母虚高——这是 GEO 类产品最隐蔽的一类错。

## 强模型 vs 本机小模型：同一批问题，第一名对调

用 Magpie 网关（本机 `127.0.0.1:3425`，聚合免费/低价模型）对同样 8 个买家问题采样。
`--provider=magpie`，模型：`deepseek-v4.1-flash`（0 价）、`deepseek-v4.1-flash-max`、`gpt-6.1-terra`。

| 品牌 | 本机 qwen3:8b | deepseek-v4.1-flash | deepseek-v4.1-flash-max | gpt-6.1-terra |
|---|---|---|---|---|
| Ramp | 12.5%（位次 1.0） | **21.6%（1.12）** | **22.2%（1.0）** | **29.6%（1.12）** |
| Brex | 12.5%（2.0） | 21.6%（2.62） | 22.2%（2.12） | 29.6%（2.38） |
| Expensify | **50.0%（1.25）** | 13.5%（4.4） | 13.9%（4.0） | 11.1%（2.0） |
| Coupa | 25.0%（1.0） | 5.4%（1.5） | — | — |
| Bill.com | — | 8.1%（5.33） | 13.9%（4.4） | 11.1%（3.33） |

**同一批问题，本机 8B 模型把 Expensify 排第一并给 50% 份额；三个云端强模型一致把 Ramp 排第一、
Expensify 掉到第三或第四。** 这不是「哪个模型更准」的主观判断，而是产品必须先回答的问题：
你卖的那份排名，是在哪个模型上测出来的。

### 三条可卖的结论

1. **强模型之间高度一致**：Ramp 极差 8.0pt、Brex 8.0pt、Expensify 2.8pt；
   而本机三模型之间从第二名开始就差 13–16pt（见上一节）。
   结论：GEO 报告必须绑定「模型档位」，跨档位混算等于造假。
2. **本机小模型不能用于 GEO**：它把「想不起更多品牌」表现为「不提及」，
   于是知名老牌（Expensify）份额被抬高、当红新牌（Ramp/Brex）被压低——
   方向性偏差，不是噪声，跑多少次都修不回来。
3. **同模型重跑稳定**：`deepseek-v4.1-flash` 跑了两轮（一次中断、一次完整），
   Ramp 22.2%→21.6%、Brex 22.2%→21.6%、Expensify 13.9%→13.5%，位次顺序不变。
   所以**模型固定时，8 条提示词就足以稳定排出前 3**，不需要上千次采样。

### 复跑

```bash
# 本机小模型（trace 慢但零成本）
python3 scripts/real_geo.py 8
# Magpie 网关（免费+低价档，需要本机 3425 在跑）
python3 scripts/real_geo.py --provider=magpie \
  --models=deepseek-v4.1-flash,deepseek-v4.1-flash-max,gpt-6.1-terra
```

`data/geo_real_<provider>.json` 保留每个模型每条提示词的原始回答，可复核每个提及。

## 跨赛道复现：三个赛道，同一个病

一个赛道不足以支撑结论，所以把同一套代码换两个赛道再跑（`--category=crm|support`）。
每个赛道 10 个候选品牌、8 条买家问题、一个强模型对一个本机小模型。

| 赛道 | 强模型前 3（deepseek-v4.1-flash） | 本机 qwen3:8b 前 3 | 本地命中品牌 |
|---|---|---|---|
| 费用管理 expense | Ramp 21.6% / Brex 21.6% / Expensify 13.5% | **Expensify 50.0%** / Coupa 25.0% / Ramp 12.5% | 5 / 10 |
| CRM | HubSpot 22.9% / Pipedrive 22.9% / Salesforce 17.1% | HubSpot 36.4% / Zoho 27.3% / Salesforce 18.2% | 4 / 10 |
| 客服 support | **Help Scout 18.9%** / Intercom 18.9% / Zendesk 18.9% | Zendesk 36.8% / Freshdesk 26.3% / Intercom 21.0% | 5 / 10 |

强模型三个赛道都点出 **8–10 个品牌**；本机小模型只有 **4–5 个**。

### 三条复现出来的规律

1. **长尾截断是稳定复现的**：CRM 赛道本地模型从未提到 Attio、Close、Folk、Monday、Copper、Freshsales
   （六个全丢）；客服赛道从未提到 Help Scout 和 Front——而这两家在强模型里分别是第一和第六。
   **越是新公司越容易在小模型里「不存在」。**
2. **份额被系统性膨胀**：本地模型给第一名的份额是 36–50%，强模型给第一名只有 19–22%。
   小模型的「份额」测的其实是「知名度」——它只会反复报那几个想得起来的名字。
3. **第一名是否对调，取决于赛道**：费用管理对调（Expensify ↔ Ramp），CRM 一致（HubSpot），
   客服赛道强模型第一是 Help Scout、本地根本没提过。所以报告不能笼统写「排名可信」，
   要写明是在哪个赛道、哪个档位、哪一批提示词上测的。

### 产品结论

GEO 报告的最低合规要求应该是三行字：**用的哪个模型、哪个档位、哪批提示词**。
缺任何一行，这份排名就不可比——因为换档位能换掉第一名，也能让一个品牌从榜单上彻底消失。

复跑：

```bash
python3 scripts/real_geo.py --category=crm     --provider=magpie --models=deepseek-v4.1-flash
python3 scripts/real_geo.py --category=crm     --provider=ollama --models=qwen3:8b
python3 scripts/real_geo.py --category=support --provider=magpie --models=deepseek-v4.1-flash
python3 scripts/real_geo.py --category=support --provider=ollama --models=qwen3:8b
```
