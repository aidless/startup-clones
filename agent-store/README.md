# agentstore

一个 agent 应用商店的最小内核：**清单（能力 + 价格）→ 不可变版本（内容摘要）→ 最小授权安装 →
执行前权限闸 → 按用量计费 → 平台分成账单**。约 1400 行、零外部依赖、只用 Python 标准库与 SQLite，
所以它适合用来读懂"商店到底难在哪"，也可以作为你自己 agent 市场的计费骨架。

它把商店最难的四条商业规则写成了代码与测试：

| 问题 | 天真做法 | 后果 | 这里的处理 |
| --- | --- | --- | --- |
| 卖家上架后偷偷改行为 | 版本号可以覆盖 | 买家装的和你审的不是一个东西 | `publish` 拒绝同版本重发，`digest` 内容哈希入表 |
| agent 悄悄读凭据 | 权限写在文档里 | 一次事故把平台告倒 | `KNOWN_PERMISSIONS` 白名单 + 安装时最小授权 + 执行前闸 |
| 被拦的请求也收费 | 请求进来就记一笔 | 账单争议拖垮客服 | `Runtime` **只在 handler 成功后写计量** |
| 客户端重投重复计费 | 每次请求都记 | 账单是实际调用的 3 倍 | `(buyer, request_id)` 是主键，第二次直接回放原记录 |

## 安装

```bash
pip install -e .            # 只跑测试再加：pip install -e ".[dev]"
```

要求 Python 3.9+（CI 覆盖 3.9 / 3.10 / 3.11 / 3.12）。

## 三分钟：跑出你自己的结果

```bash
python3 -m agentstore.cli quickstart
```

在当前目录生成 `agentstore-quickstart/`，打完会打印接下来三条命令（真实输出）：

```
== quickstart: agentstore-quickstart（新建/覆盖 4 个，跳过 0 个）==
  create    agents/hello/agent.json
  create    agents/hello/handler.py
  create    README.md
  create    run.py

接下来三条命令：
  1) cd agentstore-quickstart
  2) python3 run.py
  3) python3 -m agentstore.cli demo
```

`python3 run.py` 走完发布 → 安装 → 带幂等键执行 → 同键重放 → 同键换载荷 → 账单（真实输出）：

```
[1 发布] hello@0.1.0 digest=c11b660ee771 开发者=you
[2 安装] you 只授予清单里的 ['fs.read']；越权的那份清单会被拒
[3 执行] ok=True id=demo-key-1 计费=5¢ 输出='HELLO AGENT STORE'
[4 重放] duplicate=True id=demo-key-1 计费=5¢ 输出='HELLO AGENT STORE'
[5 换载荷] ok=False error=idempotency_conflict: 该键已用于 hello@0.1.0，本次载荷不同
[6 账单]
# 账单 · you

| agent | 开发者 | 调用 | 计量单位 | 应付 | 平台分成 | 开发者应得 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| hello | you | 1 | 1 | $0.05 | $0.01 | $0.04 |

合计应付 **$0.05**（平台抽成 20%）

库里的用量行数：1（重放与冲突都没有新增计费）
```

三行重点：`[3]` 第一次真跑并记一次账；`[4]` 同一个键回放**同一次执行**（`id` 相同、
`duplicate=True`）且不再执行 handler、不再计费；`[5]` 同一个键换了载荷直接拒。

重复执行 `quickstart` 不会覆盖你改过的文件（存在则打印 `skip`）；要重置加 `--force`。
生成的 `agents/hello/handler.py` 只 import 标准库，`AGENTSTORE_INPUT="ship it" python3 run.py`
就能换载荷，不用改代码。

## 自己写代码时（与 quickstart 同一套 API）

```python
from agentstore.manifest import load_manifest
from agentstore.meter import Ledger
from agentstore.registry import Registry
from agentstore.runtime import Runtime

manifest = load_manifest("agents/hello/agent.json")     # 清单 + 校验
needs = tuple(manifest.needs)                           # 调用期真正要的权限，⊆ permissions

registry = Registry("store.db")
ledger = Ledger("store.db")
ledger.register(manifest)                               # 计量需要清单里的价格
registry.publish(manifest, "you")                       # 同版本重发会被拒
registry.install("you", manifest.agent_id, granted=needs)   # 最小授权安装

runtime = Runtime(registry, ledger)
first = runtime.execute("you", manifest.agent_id, handler, "key-1", needs=needs)
again = runtime.execute("you", manifest.agent_id, handler, "key-1", needs=needs)
assert again.id == first.id and again.duplicate          # 同键同载荷 → 回放同一次执行

bad = runtime.execute("you", manifest.agent_id, handler, "key-1", needs=needs, tokens=999)
assert bad.ok is False and bad.error.startswith("idempotency_conflict")
```

`handler` 的契约是 `handler(request_id) -> (output, units)`：`units` 是计量单位数
（按次恒为 1；按 token 是 token 数；订阅被忽略）。

## 计量与分成怎么读

| 计费方式 | 计量单位 | 舍入 | 适合 |
| --- | --- | --- | --- |
| `per_call` | 每次成功调用 | 精确到美分 | 确定性工具类 agent |
| `per_token` | 每 1k token | **向上取整**到 1k（不足 1k 按 1k） | 生成类 agent，成本主要是模型费 |
| `subscription` | 每周期 | 一次性 | 常驻/看板类 agent |

分成规则：`platform = round(gross × fee%)`，**余数归开发者** —— 舍入误差不能让平台白赚钱，
否则开发者对账永远差几分钱（`test_split_rounding_favours_developer` 钉住这条）。
`statement` 先按总额取整再逐行分配、末行兜底，保证 `platform + developer == gross` 逐行与合计都成立。

出账有两个入口：人读的 Markdown 与 `--json`（金额单位是整数美分）。

```bash
rm -f /tmp/agentstore.db          # demo 每次都重新发布 3 个 agent，重跑前先删库
python3 -m agentstore.cli demo --db /tmp/agentstore.db
python3 -m agentstore.cli statement --db /tmp/agentstore.db --buyer acme \
  --developer invoice-bot=northwind-labs --developer deck-research=quill-research \
  --developer cfo-copilot=ledgerly --request-id st-2026-11 --json
```

`--request-id` 是**出账**的幂等键（scope 到 buyer）：同一个 id 再来原样回放首次快照，
并把 `idempotent_replay` 置真 —— 回放连 `fee_pct` 一起回，所以拿到的可能是旧口径的数；
要按新口径出账必须换新 id。没给 `--developer` 的 agent 记 `unknown`（`usage` 只记用量，不记归属）。
退出码：`0` 跑通，`2` 用法错（缺 `--db`/`--buyer`、`--fee-pct` 不在 0..100、`--developer` 不是 `agent=dev`）。

## 代码地图

```
manifest.py  AgentManifest / Pricing / 权限白名单 / canonical digest / semver / load_manifest
registry.py  publish（不可覆盖）/ yank / latest / install（最小授权）/ granted
runtime.py   resolve → status → gate(权限) → execute → meter（失败与拦截都不计费）
meter.py     Ledger：request_id 幂等 + 指纹、三种定价、Statement 分账、出账快照
quickstart.py 生成 agentstore-quickstart/ 工作区（可重复执行，不覆盖用户改动）
fixtures.py  invoice-bot(按次) / deck-research(按 token) / cfo-copilot(订阅)
cli.py       quickstart / demo / statement
```

## 路线图

- [x] 清单 / 不可变版本 / 权限闸 / 幂等计量 / 分成账单 / quickstart
- [ ] 清单签名（Ed25519，公钥在商店侧），防止中间人替换 `agent.json`
- [ ] 执行隔离（子进程 + seccomp / 容器），当前 `handler` 是进程内回调
- [ ] 订阅周期结算（本版本把订阅当单次记账，缺少周期边界与按比例退款）
- [ ] 退款/争议流程（`usage` 表需要 `reversed_by` 与不可变审计链）
- [ ] 商店侧审核状态机（draft → in_review → published → yanked）

## 已知边界

- **出账快照落成即冻结，`issued_at` 不是墙钟**：给了 `--request-id` 时，`gross/platform/developer/rows`
  连同 `fee_pct` 一起写进 `statements` 表（`meter.py:257`），此后同一 `(buyer, request_id)` 一律回放
  （`meter.py:245`）—— 新增用量、新的 `--fee-pct` 都看不到；要重算必须换 id。`issued_at` 取 `Ledger._now`
  （`meter.py:150`，默认硬编码 `2026-11-12T00:00:00Z`），是注入的测试时钟而非真实时间，接真系统时
  必须注入墙钟，否则所有快照的时间戳都相同。
- **金额用整数分，但账单只覆盖记进 `usage` 表的事件**：`Pricing.cents_per_unit` 与 `usage.cents` 都是整数（`manifest.py:32`、`meter.py:20`），展示时才用 `Decimal` 转美元（`meter.py:50`）。被权限闸拦下、handler 抛错、以及同 `(buyer, request_id)` 的重投都不会写 usage（`runtime.py:74`、`runtime.py:132`），所以账单里没有这些调用；反过来，绕过 `Runtime` 直接调 `Ledger.record` 的用量不受任何前置校验约束。整数分也做不了「$0.000003/token」这种粒度，真实系统应按 micro-cent 存整数。
- **版本归属以首次发布为准，不能转移**：`publish` 用 `INSERT OR IGNORE` 写入 `agents.developer`（`registry.py:77`），此后的发布者必须与首发布者一致（`registry.py:71`），没有转让或迁移归属的 API；`yank` 只改状态、不删版本（`registry.py:88`），买家已有安装仍保留记录。
- **分成先按总额取整、再逐行分配、末行兜底**：`statement` 先算 `target_fee`（`meter.py:226`），中间行各自取整并被夹在剩余额度内，最后一行拿走全部余额（`meter.py:229`），保证 `sum(platform) + sum(developer) == gross`。代价是每行金额依赖行顺序，不能对单行独立复算；抽成比例是账单参数（`statement(..., fee_pct=20)`）而不是合同。
- **registry 是单文件 SQLite，没有并发写保护**：`Registry` 直接 `sqlite3.connect(db_path)`（`registry.py:55`），默认 `:memory:`，未开 WAL、未设 `busy_timeout`、也没有进程内锁或重试；多进程/多线程同时 `publish`/`install` 会撞上 `database is locked` 或丢写。（`Ledger` 那边是另一套连接：`busy_timeout=5000` 且非 `:memory:` 开 WAL，`meter.py:130`。）
- **没有真实支付网络对接**：整个包没有任何网络请求或支付 SDK 调用。`payment.charge` 只是 `KNOWN_PERMISSIONS` 里的一个权限字符串（`manifest.py:19`），账单是本地 `usage` 表的聚合与 Markdown 渲染（`meter.py:118`），扣款、退款、对账、发票都留给外部系统。
- **digest 是内容哈希，不是签名**：`digest()` 只做 `sha256(canonical)`（`manifest.py:83`），能查出「同版本内容改了」，但证明不了「这份清单是开发者发的」；签名、执行隔离仍在路线图（`handler` 目前是进程内回调，`runtime.py:123`）。同理 `needs` 参与摘要只保证「装完之后要什么权限」没被偷改，不保证权限列表本身经过审核。
  另外：`needs` 是 0.1.0 之后加进 `canonical()` 的（`manifest.py:77`），所以**同一份清单的 digest
  与旧版不同**——摘要覆盖的字段变了。库里已有旧摘要的版本按「改内容就必须发新版本号」处理，
  不要在旧版本上原地覆盖。

## 附：为什么要有权限声明（2026-11 的一次实测）

`scripts/fetch_mcp_servers.py` 从 GitHub 按 `mcp-server in:name` 取星标最高的仓库，
拉 `package.json` 与 `README.md`，剔除 awesome-* 清单仓库后留下 **16 个真实 server**，
再由 `scripts/real_manifests.py` 对每份跑入市审查。

| 指标 | 结果 |
|---|---|
| 清单里有任何权限字段（permissions/capabilities/scopes/mcp） | **0 / 16** |
| 文档/依赖显示需要 API 密钥 | 13 / 16 |
| 需要写文件 | 1 / 16 |
| 版本可固定（x.y.z） | 9 / 16 |

零声明不是样本太少——这 16 个合计超过 10 万星标，含 GitHub、Cloudflare、Notion、Firecrawl
的官方 server。买家装这些东西时，没有任何机器可读的东西告诉他这个 agent 能不能读文件、
能不能拿 token。这条事实决定了商店该做什么：不是托管，而是**替买家把没写的东西补出来**，
并让补出来的结论进入安装决策。同样这轮实测把「要写文件」从 9 份修到 1 份（`credits` 里的
`edit`、`actions/checkout` 两个假阳性），假阳性比漏报更贵。

重跑：

```bash
python3 scripts/fetch_mcp_servers.py 20   # 抓清单（写 data/raw/，已 gitignore）
python3 scripts/real_manifests.py         # 审查 + 打印结论表
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
