# agent-store

agent 应用商店的最小可运行内核：**清单（能力 + 价格）→ 不可变版本 → 最小授权安装 → 执行前权限闸 → 按用量计费 → 平台分成账单**。

> 对标：Cowboy（纽约，2026 年 $5M 种子，创始人 Chad DePue）。它做「agent 的应用商店 + 托管 + 分成」。这里把商店最难的四条商业规则写成代码和测试。

## 商店的四个生死问题

| 问题 | 天真做法 | 后果 | 本项目的处理 |
| --- | --- | --- | --- |
| 卖家上架后偷偷改行为 | 版本号可以覆盖 | 买家装的和你审的不是一个东西 | `publish` 拒绝同版本重发，`digest` 内容哈希入表 |
| agent 悄悄读凭据 | 权限写在文档里 | 一次事故把平台告倒 | `KNOWN_PERMISSIONS` 白名单 + 安装时最小授权 + 执行前 `gate` |
| 被拦的请求也收费 | 请求进来就记一笔 | 账单争议，退款流程拖垮客服 | `Runtime` **只在 handler 成功后写计量** |
| 客户端重投重复计费 | 每次请求都记 | 客户发现账单是实际调用的 3 倍 | `request_id` 是 usage 表主键，第二次直接返回原记录 |

## 快速开始

```bash
cd agent-store
pip install -e .
python -m agentstore.cli        # 3 个 agent 上架 → 最小授权 → 6 次调用 → 出账单 → 反例
```

## 演示输出（真实运行）

```
== 上架 ==
  invoice-bot@1.2.0   per_call     digest=b47b8d3bd19a  by northwind-labs
  deck-research@0.4.1 per_token    digest=254e4f45d55f  by quill-research
  cfo-copilot@2.0.0   subscription digest=f251bc4d0b7d  by ledgerly

[OK ] invoice-bot@1.2.0 $0.05
[ERR] deck-research@0.4.1 免费
  permission_denied: secrets.read
[OK ] deck-research@0.4.1 $0.90          ← 2400 token 按 3 个 1k 计
[OK ] cfo-copilot@2.0.0 $9.00
[OK ] invoice-bot@1.2.0 $0.05            ← 与 req-1001 同 id，账单里仍只算 1 次

# 账单 · acme
| agent | 开发者 | 调用 | 计量单位 | 应付 | 平台分成 | 开发者应得 |
| cfo-copilot | ledgerly | 1 | 1 | $9.00 | $1.80 | $7.20 |
| deck-research | quill-research | 1 | 2400 | $0.90 | $0.18 | $0.72 |
| invoice-bot | northwind-labs | 2 | 2 | $0.10 | $0.02 | $0.08 |
合计应付 **$10.00**（平台抽成 20%）

== 反例：改内容不发新版本 ==
  已拒绝：invoice-bot@1.2.0 已发布（digest=b47b8d3bd19a）；改内容必须发新版本号
```

## 三个计费口径

| 方式 | 计量单位 | 舍入规则 | 适合 |
| --- | --- | --- | --- |
| `per_call` | 每次成功调用 | 精确到美分 | 确定性工具类 agent |
| `per_token` | 每 1k token | **向上取整**到 1k（不足 1k 按 1k） | 生成类 agent，成本主要是模型费 |
| `subscription` | 每周期 | 一次性 | 常驻/看板类 agent |

分成：`platform = round(gross × fee%)`，**余数归开发者** —— 舍入误差不能让平台白赚钱，否则开发者对账永远差几分钱（`test_split_rounding_favours_developer` 钉住这条）。

## 架构

```
manifest.py  AgentManifest / Pricing / 权限白名单 / canonical digest / semver
registry.py  publish（不可覆盖）/ yank / latest / install（最小授权）/ granted
runtime.py   resolve → status → gate(权限) → execute → meter（失败与拦截都不计费）
meter.py     Ledger：request_id 幂等、三种定价、Statement 分账
fixtures.py  invoice-bot(按次) / deck-research(按 token) / cfo-copilot(订阅)
cli.py       demo
```

## 路线图

- [x] 清单 / 不可变版本 / 权限闸 / 幂等计量 / 分成账单
- [ ] 清单签名（Ed25519，公钥在商店侧），防止中间人替换 `manifest.json`
- [ ] 执行隔离（子进程 + seccomp / 容器），当前 `handler` 是进程内回调
- [ ] 订阅周期结算（本版本把订阅当单次记账，缺少周期边界与按比例退款）
- [ ] 退款/争议流程（`usage` 表需要 `reversed_by` 与不可变审计链）
- [ ] 商店侧审核状态机（draft → in_review → published → yanked）

## 已知边界

- **金额用整数分，但账单只覆盖记进 `usage` 表的事件**：`Pricing.cents_per_unit` 与 `usage.cents` 都是整数（`manifest.py:32`、`meter.py:19`），展示时才用 `Decimal` 转美元（`meter.py:28`）。被权限闸拦下、handler 抛错、以及同 `(buyer, request_id)` 的重投都不会写 usage（`runtime.py:71`、`runtime.py:81`、`runtime.py:55`），所以账单里没有这些调用；反过来，绕过 `Runtime` 直接调 `Ledger.record` 的用量不受任何前置校验约束。整数分也做不了「$0.000003/token」这种粒度，真实系统应按 micro-cent 存整数。
- **版本归属以首次发布为准，不能转移**：`publish` 用 `INSERT OR IGNORE` 写入 `agents.developer`（`registry.py:77`），此后的发布者必须与首发布者一致（`registry.py:73`），没有转让或迁移归属的 API；`yank` 只改状态、不删版本（`registry.py:86`），买家已有安装仍保留记录。
- **分成先按总额取整、再逐行分配、末行兜底**：`statement` 先算 `target_fee`（`meter.py:130`），中间行各自取整并被夹在剩余额度内，最后一行拿走全部余额（`meter.py:132`），保证 `sum(platform) + sum(developer) == gross`。代价是每行金额依赖行顺序，不能对单行独立复算；抽成比例是账单参数（`statement(..., fee_pct=20)`）而不是合同。
- **registry 是单文件 SQLite，没有并发写保护**：`Registry` 直接 `sqlite3.connect(db_path)`（`registry.py:55`），默认 `:memory:`，未开 WAL、未设 `busy_timeout`、也没有进程内锁或重试；多进程/多线程同时 `publish`/`install` 会撞上 `database is locked` 或丢写。
- **没有真实支付网络对接**：整个包没有任何网络请求或支付 SDK 调用。`payment.charge` 只是 `KNOWN_PERMISSIONS` 里的一个权限字符串（`manifest.py:19`），账单是本地 `usage` 表的聚合与 Markdown 渲染（`meter.py:119`），扣款、退款、对账、发票都留给外部系统。
- **digest 是内容哈希，不是签名**：`digest()` 只做 `sha256(canonical)`（`manifest.py:75`），能查出「同版本内容改了」，但证明不了「这份清单是开发者发的」；签名、执行隔离仍在路线图（`handler` 目前是进程内回调，`runtime.py:80`）。

MIT License.

## 真实数据：16 个 MCP server 的清单审查

`scripts/fetch_mcp_servers.py` 从 GitHub 按 `mcp-server in:name` 取星标最高的仓库，
拉 `package.json` 与 `README.md`（各 6000 字上限），剔除 3 个 awesome-* 清单仓库，
留下 **16 个真实 server**。`scripts/real_manifests.py` 对每份跑入市审查。

### 结论一：权限声明在这个生态里不存在

| 指标 | 结果 |
|---|---|
| 清单里有任何权限字段（permissions/capabilities/scopes/mcp） | **0 / 16** |
| 文档/依赖显示需要 API 密钥 | 13 / 16 |
| 需要写文件 | 1 / 16 |
| 版本可固定（x.y.z） | 9 / 16 |

零声明不是「我们样本少」——这 16 个加起来超过 10 万星标，包括 GitHub、
Cloudflare、Notion、Firecrawl 的官方 server。买家在装这些东西时，
**没有任何机器可读的东西告诉他这个 agent 能不能读你的文件、能不能拿你的 token。**

这条事实直接决定商店该做什么：不是托管，不是计费，而是**替买家把没写的东西补出来**，
并且让「补出来的结论」进入安装决策。

### 结论二：分级要按证据强度，不按关键词数量

真实跑出来的等级分布：**high 5 / medium 11**。

- high 的 5 家（shadcn-ui / apify / browserbase / financial-datasets / firecrawl）
  都在 README 里写出了具体环境变量名（`BROWSERBASE_API_KEY`、`FIRECRAWL_API_KEY`…）——
  这是硬证据：它一定要拿凭据去调外部服务。
- 其余只出现 `token`/`auth` 这类泛词，判 medium：可能是讲别人的东西，也可能是自述需求。

如果一上来按关键词数量定 high，16 份全是 high，审查结论就没有区分度了。

### 已修的两个假阳性（都是真实数据逼出来的）

| 现象 | 原因 | 修法 |
|---|---|---|
| 9 份清单被判「要写文件」 | `"edit" in text` 命中了 `credits` 里的 edit | 关键词改词边界匹配（`(?<![a-z0-9])kw(?![a-z0-9])`），写文件降到 1 份 |
| GitHub 官方 server 被判「要动钱」 | `checkout` 命中了 `actions/checkout` | 从付款词表删掉 `checkout`，付款需求降到 0 份 |

假阳性比漏报更贵：一份把 GitHub 说成收款工具的审查报告，会让整份报告没人相信。

### 重跑

```bash
python3 scripts/fetch_mcp_servers.py 20   # 抓清单（写 data/raw/，已 gitignore）
python3 scripts/real_manifests.py         # 审查 + 打印结论表
```
