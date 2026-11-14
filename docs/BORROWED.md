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
