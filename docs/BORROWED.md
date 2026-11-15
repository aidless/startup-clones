# 他山之石：从外部成熟实现借来的机制

> 2026-11-14。用户一句「他山之石，可以攻玉」。规则：**先读外部实现的文档，再动自己的代码**；
> 借的是机制与判据，不是代码搬运；每一条都要能在本项目里指出落点 `文件:行`，
> 并且**先在旧实现上写出会红的测试**（AGENTS.md 第 27 条）。

来源核验方式：全部 `web_fetch` 官方文档页，日期 2026-11-14；链接即原文。

## 一、已落地（4 条，20 个测试）

| # | 借什么 | 来源 | 落点 | 判据（会红的测试） |
|---|---|---|---|---|
| B-1 | Wilson score 区间，替代比例的裸点估计 | [Inspect · Scoring Metrics](https://inspect.aisi.org.uk/metrics.html) `ci_wilson()`：*「二元得分优先用它，边界恒在 [0,1]，小样本与比例贴近 0/1 时更校准」* | `cruxline/cruxline/stats.py:15`（`wilson_interval`）、`cruxline/cruxline/regress.py:30`（`intervals`）、`:54`（markdown 的 95% CI 行） | `cruxline/tests/test_borrowed_stats.py`：59/60 → `[91.15%, 99.71%]`；0/10 的下界是 0 但上界 ~30%（不是「0% 确定」）；区间随 n 变小而变宽；`k>n`/`n=0` 抛 ValueError |
| B-2 | 用例集指纹：报告必须写「这次量的是哪一批用例」 | [Inspect · Eval Sets](https://inspect.aisi.org.uk/eval-sets.html)：*靠稳定 sample id 复用已完成样本，自动自增 id 在 shuffle 下失效* | `cruxline/cruxline/stats.py:35`（`set_fingerprint`）、`regress.py:23`（`fingerprint` 字段）、`:80`（`diff()` 里写入） | 同一批 id 换顺序指纹相同、换成员不同；`to_markdown()` 必须同时出现 `95% CI` 与指纹 |
| B-3 | bootstrap 百分位区间 + 固定 seed | [Inspect · Scoring Metrics](https://inspect.aisi.org.uk/metrics.html) `bootstrap_stderr()`（默认 1000 次重采样）、`ci(method="bootstrap")` | `geo-radar/georadar/stats.py:15`（`bootstrap_ci`）、`:39`（`proportion_ci`）、`georadar/report.py:59`（出现率列）、`:115`（口径脚注） | `geo-radar/tests/test_borrowed_stats.py`：同样的输入必须印同一个区间（可复核）；11/32 的区间宽度 > 15 个百分点（N=32 本该宽）；110/320 的宽度必须小于前者一半；空/全等输入退化不抛 |
| B-4 | From 头按 RFC 5322 解析，不自造正则 | [RFC 5322 §3.4](https://www.rfc-editor.org/rfc/rfc5322#section-3.4) + 标准库 `email.utils.getaddresses` | `agent-inbox/agentinbox/channels.py:55`（`sender_address`，地址解析在 `:64`） | `agent-inbox/tests/test_borrowed_rfc5322.py`：`(support@acme.example) bob@partner.example` 必须解析成 `bob@…`（旧实现在这里把注释里的地址当发件人 → 按内部域名放行）；原有伪装写法 `"Alice <alice@acme.example>" <attacker@evil.example>` 仍解析到 attacker；显示名带逗号不拆 |
| B-5 | 摘要必须在消费点复核（integrity），而不是只存不验 | npm `dist.integrity` / [sigstore](https://www.sigstore.dev/) 的「签名跟着产物走，安装时验」 | `agent-store/agentstore/registry.py:119`（`install`，摘要比对在 `:125-128`） | `agent-store/tests/test_borrowed_integrity.py`：直接改库里 `manifest` 列为 `payment.charge` 后 `install` 必须抛 `RegistryError("…摘要…")`；干净安装不受影响 |

为什么 B-1/B-3 都做，不抽成共享库：七个项目各自可独立安装/出售（`pyproject` 各自声明依赖），
跨项目 `import` 会把发布单元焊死。两处各 30 行，代价小于耦合；`docs/POLISH.md` 里「异常无共享基类」
是同一个取舍的另一面。

**区间只用在真是抽样的地方**：geo-radar 的 32 条是模型采样，抽样性成立，所以印区间；
cruxline 的 60 条轨迹是**确定性重放**，逐条差异（回归/修复清单）才是判据，所以区间只作为
「若把这批当抽样」的旁注印，**不参与 verdict**。把统计显著性套在确定性重放上，
会让 `regressions` 为空、`delta>0` 的真改善被判成「不显著」——那是把尺用错底物（第 37 条）。

## 二、读了但没落地（连同不落地的理由）

| 机制 | 来源 | 为什么不借 |
|---|---|---|
| `krippendorff_alpha()` 多裁判一致性 | Inspect metrics | 需要 ≥3 个独立 judge 对同一批判例打分。本项目只有一个 rubric judge；`calib.py` 现在的 kappa 是「judge vs 人工标注」两列，α 与 κ 在这形状上等价，换名不换信息。等真的接第二个 judge 再上 |
| epoch reducer（`pass_at_k` / `at_least_k` / `collect`） | Inspect metrics | 前提是同一 sample 跑多 epoch。cruxline 每条轨迹是实录，没有 epoch 维度；硬造会在报表里多一列没人用的数字 |
| `grouped()` / `stderr(cluster=...)` 分组与聚类标准误 | Inspect metrics | 分组前提是 metadata 有稳定分类字段。geo-radar 的 category 是自由文本，先补受控词表才有意义（已记在 `docs/POLISH.md` 待办） |
| semver 单调递增校验 | npm 发布规则 | `publish()` 已用 `SEMVER_RE` 校验格式，`latest()` 按 `parse_version` 数值排序，回退发布不会抢到「最新」；再加一道只会多一条永不被触发的分支 |
| content-addressed 存储（内容哈希做键） | npm / OCI | 现在 `versions` 表用 `(agent_id, version)` 主键 + digest 校验已足够；改成 CAS 要重写 `_dump/_load` 与全部查询，收益是「同内容去重」，这个库不需要 |

## 三、顺序与验证

```bash
cd startup-clones
python3 -m pytest cruxline/tests/test_borrowed_stats.py geo-radar/tests/test_borrowed_stats.py \
                 agent-inbox/tests/test_borrowed_rfc5322.py agent-store/tests/test_borrowed_integrity.py -q  # 20 passed
python3 -m pytest -q      # 396 passed（借入前 331，借入后 351，第二轮回补后 396）
python3 scripts/polish_audit.py   # 7 个项目硬项全过
```

先红后绿的证据：新测试在实现前跑过一次——`cruxline`/`geo-radar` 是 `ModuleNotFoundError:
No module named 'cruxline.stats' / 'georadar.stats'`；`agent-inbox` 是
`FAILED test_comment_embedded_address_is_not_the_sender`；`agent-store` 是
`Failed: DID NOT RAISE RegistryError`。四个都因「机制不在」而红，不是因为断言写错。

## 第二轮（2026-11-14）：幂等键指纹 + sqlite 的等待与 WAL + 问题文档

第一轮借的是「怎么量」（区间、指纹、解析、验签），这一轮借的是**「怎么不出错」**——
三个机制都在回答同一个问题：调用方重投一次、两个进程同时写一次、参数传错一次，会怎样。

| # | 借来的机制 | 来源（原文要点） | 落点 | 判据（先红后绿） |
|---|---|---|---|---|
| C-1 | 幂等键必须唯一，且**不得用于不同载荷**；复用不同载荷 → 冲突 | [draft-ietf-httpapi-idempotency-key-header-08](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header) §2.2 *「The idempotency key MUST be unique and MUST NOT be reused with another request with a different request payload」*；§2.4 指纹由 payload 生成；§2.6 已完成→按用户意图回放、**未完成→资源冲突**；§2.7 复用不同 payload → `422` | `agent-store/agentstore/runtime.py:52`（`request_fingerprint`：`agent` + 排序后的 `needs` + `tokens` 的 sha256 前 16 位）、`:70`（重放前先比指纹，不同则返回 `idempotency_conflict`）、`agentstore/meter.py`（`usage.fingerprint` 列 + `_migrate_usage` 兼容旧库 + `replay()` 读回指纹） | `agent-store/tests/test_borrowed_idempotency.py`：同键换 agent / 加 tokens → 冲突且 `duplicate=False`；**同一载荷重投仍是回放**（`duplicate=True`，handler 只跑一次）；旧库无该列时自动迁移 |
| C-2 | 写者要**等锁**，读者不要被写者堵住 | [sqlite.org/wal.html](https://sqlite.org/wal.html) §1 *「Readers do not block writers and a writer does not block readers」*；§9 **WAL 下仍可能返回 SQLITE_BUSY**（独占锁/最后一个连接关闭/崩溃恢复）→ 必须配 `busy_timeout` | `agent-store/agentstore/meter.py:130`（`_connect`：`timeout=5.0` + `PRAGMA busy_timeout=5000` + 文件库 `PRAGMA journal_mode=WAL`）、`geo-radar/georadar/store.py:53`（`_tune`）、`filing-lens/filinglens/facts.py:104`、`cruxline/cruxline/store.py:24` | `agent-store/tests/test_borrowed_idempotency.py::test_ledger_waits_for_a_lock_instead_of_failing`（另一连接 `BEGIN IMMEDIATE` 后，写者 0.4 秒仍在等，提交后成功写入）、`geo-radar/tests/test_borrowed_sqlite.py`、`filing-lens/tests/test_borrowed_sqlite.py`、`cruxline/tests/test_borrowed_sqlite.py`（各 2 例：文件库 `journal_mode=wal` 且 `busy_timeout>=1000`；`:memory:` 正对照不报错） |
| C-3 | 错误响应是**一种文档格式**，不是随便一个 `{"error": …}` | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)：`type`/`title`/`status`/`detail`/`instance` + 媒体类型 `application/problem+json` | `console/app.py:50`（`problem()`）、`:63`（`RequestValidationError` 处理器，逐条错误放 `errors` 扩展）、`:126`（`/api/filing` 的 CIK 格式校验 → 400） | `console/tests/test_problem_json.py`：坏 CIK → 400 且 `content-type: application/problem+json`、四成员齐全、`status` 与 HTTP 状态一致；`q` 太短 → 422 且带 `errors`；**两个正对照**——「本地没这份 10-K」仍是 200 + `status=no_data`（面板要就地解释，不是错误），正常回答仍是普通 `application/json` 且不含 `type` |

顺带修掉一个输入拼接：`/api/filing` 原先把 `cik` 直接插进 `glob(f"{cik}_10k_*.htm")`，
`cik=*` 会命中别家公司的文件。现在先按 `^\d{1,10}$` 校验再 `zfill(10)`。

### 读了但没借（第二轮）

| 机制 | 来源 | 为什么不借 |
|---|---|---|
| 幂等键 24 小时过期 | Stripe `Idempotency-Key` 的实现约定 | 我们的键是调用方自带的 `request_id`，落在 `usage` 表里就是账单凭证；过期删除等于删账。要清理由使用方按审计周期决定，写死 24h 会把「迟到的重投」变成二次计费 |
| 冲突响应一律 422 | idempotency-key §2.7 | 原文对**未完成**的并发请求给 `409`，只有「已完成 + 不同载荷」才是 `422`。我们只有单进程内存 `_done` + 库，没有长事务，所以只实现 422 这一支；等真接异步执行再补 409 |
| 把 `sqlite` 升级到 ≥3.51.3 绕开 WAL-reset bug | [wal.html §11](https://sqlite.org/wal.html)（bug 覆盖 3.7.0–3.51.2，3.51.3 修） | 本机是 3.45.1，bug 存在，但触发条件是**两个连接同时写/checkpoint**且在 checkpoint 中重置 WAL——官方措辞是概率与「SSD 故障、宇宙射线」同级。为它绑死 Python 版本不划算；已在 `filing-lens/README.md` 与本文记为已知边界 |
| 幂等键的固定格式（如 UUID v4）| idempotency-key §2.2 | 现有 `request_id` 来自调用方（`req-1`、`req-lock`），测试与演示都靠可读 id。强制 UUID 只会让日志更难读，唯一性由 `PRIMARY KEY (buyer, request_id)` 保证 |

### 验证

```bash
cd startup-clones
python3 -m pytest agent-store/tests/test_borrowed_idempotency.py \
                 geo-radar/tests/test_borrowed_sqlite.py \
                 filing-lens/tests/test_borrowed_sqlite.py \
                 cruxline/tests/test_borrowed_sqlite.py \
                 console/tests/test_problem_json.py -q      # 16 passed
python3 -m pytest -q                                        # 全套件
```

先红后绿的证据：C-1 首跑 `AttributeError: 'tuple' object has no attribute 'version'`（我把
`_done` 的值改成 `(Execution, fingerprint)` 后有一处还在用旧元组）与
`AssertionError: 写者没等锁就返回了`（测试自己在主线程建了连接却拿到子线程用——
sqlite 默认 `check_same_thread=True`，先抛 `ProgrammingError` 根本走不到锁）；C-2 三份新测试
全是 `assert 'delete' == 'wal'`；C-3 两份是 `AssertionError: application/json`。
四个红都不是断言写错，而是机制不在。
