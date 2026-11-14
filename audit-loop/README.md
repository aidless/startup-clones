# audit-loop

给中小会计师事务所的**审计底稿自动化内核**：银行余额调节、应收账龄、收入截止测试、重复付款检测 —— 输出例外清单 + 可直接归档的 Excel 底稿。

> 对标：Clark（纽约，2026-11-02 $11M 种子，Touring Capital 领投，累计 $16M）。它卖「自主 AI 审计员」给 CPA 事务所。这里做它的可验证内核，并且把「哪一步该由人判断」写死在代码里。

## 分析性程序（对真实财报跑过）

抽查凭证能抓错账，抓不到「账本身在讲故事」。`analytics.py` 判断的是比率与趋势是否自相矛盾——
这是审计里最省人力的一道程序，也是唯一能对整年数据下结论的一道。

| 程序 | 触发条件 | 说明 |
| --- | --- | --- |
| `revenue_vs_receivables` | 应收增速 − 收入增速 > 20pt | 渠道压货 / 提前确认收入；差 > 40pt 记 high |
| `gross_margin_trend` | 毛利率同比变动 > 3pt | 成本归集或分类口径被改动 |
| `cash_conversion` | 经营现金流/收入 下滑 > 10pt 或相对下滑 > 25% | 利润没变成现金 |

用真实 XBRL 跑（Apple / Microsoft FY2026 10-K，数据由 `filing-lens/scripts/fetch_edgar.py` 下载）：

```bash
python scripts/real_analytics.py ../filing-lens/data/0000320193_facts.json
```

```
Apple Inc.  收入年数=8  应收=18  毛利=18  经营现金流=15
收入序列: {2019: 260174M, 2020: 274515M, 2021: 365817M, 2022: 394328M,
          2023: 383285M, 2024: 391035M, 2025: 416161M, 2026: 478834M}

2 条例外：
  [medium] FY2021  analytics.revenue_vs_receivables
           应收账款增速 +63.0% 高于收入增速 +33.3%（差 +29.8pt），需检查是否存在提前确认收入或渠道压货
  [medium] FY2021  analytics.gross_margin_trend
           毛利率由 FY2020 的 38.2% 变为 41.8%（+3.5pt），需确认成本归集与分类口径是否变化
```

Microsoft 同口径 9 年数据无例外 —— 阈值不是「总会报」，这是它没变成装饰的证明。

## 为什么审计比多数 AI 场景更适合工程化

1. **程序是确定的**。余额调节、账龄、截止测试有明确规则和明确输出（例外清单），不需要模型发挥。
2. **交付物就是底稿**。会计师要的不是聊天记录，是能签字归档的 Excel + 一句「这 3 条要调整」。
3. **错误可被定义**。审计的失败模式是「漏掉例外」和「造出假例外」，两者都能用夹具断言。这就是本项目测试做的事。

## 核心纪律（每一条都有测试兜底）

| 纪律 | 为什么 | 落点 |
| --- | --- | --- |
| 每个程序必须挂一个审计认定 | 复核人先看「截止测试做了没」，不是「跑了几个脚本」 | `models.py` 六个认定常量 |
| 单步失败不终止整轮 | 现场数据永远有脏行；报错就停会被当成软件坏了 | `engine.py` try/except → `status=error` + `ref=ENGINE` 例外 |
| 只调节现金类科目 | 拿管理费用去碰银行流水会造出一堆假例外（本项目实测踩到） | `checks.reconcile_bank(accounts=...)` |
| 调节差额必须能手工验算 | 底稿要能被第三方重算 | `ReconResult.difference` |
| 底稿三页固定 | 摘要给合伙人 / 例外给现场 / 明细给复核 | `workpaper.py` |

## 快速开始

```bash
cd audit-loop
pip install -e .

python -m auditloop.cli demo     # 内置 Acme Industrial 夹具，埋了 6 类例外
python -m auditloop.cli run --entity "某制造有限公司" --out out/workpaper.xlsx
```

真实接入：把 ERP 导出的总账、银行流水、销售发票按 `models.py` 的三个 dataclass 逐行构造即可，字段都能从标准导出表直接映射。

## 演示输出（真实运行）

```
# 审计执行摘要 · Acme Industrial
- 期末：2026-09-30
- 结论：attention_required（high 例外 3 条）

| 程序 | 认定 | 状态 | 例外 |
| bank_recon        | 存在性     | ok | 4 |
| ar_aging          | 计价与分摊 | ok | 1 |
| revenue_cutoff    | 截止       | ok | 2 |
| duplicate_payment | 存在性     | ok | 1 |
| ar_sanity         | 计价与分摊 | ok | 1 |
| ar_completeness   | 完整性     | ok | 1 |

| duplicate_payment | 存在性 | high | G3/G6 | Northwind 在 09-20 与 09-21 各付 800.00，疑似重复付款 |
| revenue_cutoff    | 截止   | high | INV-1003 | 收入确认日 09-30 早于发货日 10-05，期末前未发货却确认收入 |
| revenue_cutoff    | 截止   | high | INV-1004 | 已确认收入但无发货记录 |
```

## 架构

```
models.py     Entry / BankLine / Invoice / Finding / StepResult + 六个审计认定
checks.py     reconcile_bank / ar_aging / revenue_cutoff / duplicate_payments / ...
engine.py     AuditRun：注册程序 → 逐个执行 → 汇总（status / high / coverage）
workpaper.py  openpyxl 三页底稿（摘要 / 例外 / 明细）
fixtures.py   埋了 6 类例外的确定性夹具
cli.py        run / analytics / demo
```

## 路线图

- [x] 三个核心程序 + 重复付款 + 数据完整性 + 底稿导出
- [ ] 函证匹配（银行/往来对账单 PDF → 结构化）
- [ ] 抽样引擎（PPS / 分层随机，含可复现随机种子）
- [ ] 上期底稿对比（哪些例外已整改、哪些重犯）
- [ ] 调整分录生成（例外 → 建议分录，人来签字）

## 已知边界

下面每一条都指到实现位置，说的是「什么情况下这份底稿的结论不可信」。

- **只做确定性检查，不做判断。** 全部检查是纯函数、无 IO、无随机（`checks.py:1-5`）；不判重要性水平、不出审计意见、不建议调整分录。`TOL = 0.01`（`checks.py:15`）是金额匹配容差，不是重要性阈值——任何金额的例外都会被列出，是否调整由会计师决定。
- **`status=clean` 不等于没问题。** `AuditRun.status` 只在「无程序报错」且「无 high 例外」时才返回 `clean`（`engine.py:66-71`），medium/low 例外可以同时存在于一份 `clean` 的底稿里；`coverage()` 报的是「程序跑了没」（`engine.py:79-81`），不是「风险覆盖了没」。
- **六类检查各有一组静默跳过条件，没报例外可能是没查。** `reconcile_bank` 只碰科目名里含 `银行存款/现金/cash/bank` 的分录，判断是**大小写不敏感**的子串匹配（`checks.py:39,50`，`Bank Account USD`/`CASH-1000` 都能进，本次打磨前的区分大小写写法会让整批英文科目匹配不上）；科目名既不含这几个词、又不是真实现金科目的（例如 `其他货币资金`）同样不参与；`duplicate_payments` 只分组 `amount < 0 and vendor` 的分录（`checks.py:146`），没填 vendor 的付款即使同日同额重复也一条例外都不出；`revenue_cutoff` 只处理 `revenue_date is not None` 的发票（`checks.py:122`），未确认收入的发票整条跳过；`ar_aging` 按发票全额、按 `due_date` 算（`checks.py:88-112`），没有回款核销匹配，部分回款的发票仍按全额在账。
- **分析性程序有单独的 CLI 出口，但不在 `run` 的底稿里。** `python -m auditloop.cli run` 仍只注册 6 个程序（`cli.py:build_run`）；三条比率/趋势检查走 `python -m auditloop.cli analytics --facts <年度序列 JSON> [--json]`（`cli.py:cmd_analytics`），退出码 0=跑完无异常 / 1=跑完有异常 / 2=没跑成。输入要调用方自己把 ERP/XBRL 导成 `revenue`/`receivables`/`gross_profit`/`cfo`：缺列或某年缺数时那条会印「数据不足」（`analytics.py:54-55,100-101`，`_num` 挡 `None`、`prev==0` 在 `analytics.py:44-48`），不再与「跑了且没问题」共用同一行输出。
- **期间与日期全是朴素 `date`，无时区、无缺省。** 期末日由调用方传入（`fixtures.PERIOD_END`），`revenue_cutoff` 的 `tolerance_days` 默认 0（`checks.py:115`）：发货日等于期末日不算例外，晚一天就算；带时间戳的导出行必须先归一到同一时区的日历日，否则 23:00 与次日 01:00 会落到相邻两天。`due_date` 为空的发票不进任何逾期桶，单列「无到期日」（`checks.py:95-99`）——算不出账龄就报不出逾期，也不会被默认算成「未到期」。
- **每条例外只带业务主键，不带源文件行号。** `Finding.ref` 是发票号/凭证号（重复付款写成 `G3/G6`，程序自身失败写成 `ENGINE`，`engine.py:49-51`）；底稿「明细」页的「行号」是导出时的顺序号 `enumerate(rows, 1)`（`workpaper.py:78`），源数据筛过行之后它与原始 Excel 行号不再对应，落到「哪个文件哪一行」得靠 ref 回原表查。也只报了这 6 类 + 3 类分析性程序能查的东西：函证、抽样、期后事项、关联方披露都不在范围内（见路线图）。
- **单步失败不会终止整轮，但会让结论降级。** 异常被捕获成 `status=error` 并注入一条 `ref=ENGINE` 的 high 例外（`engine.py:46-53`），整体 `status` 变成 `degraded`（`engine.py:67-68`）；此时「其余程序都 ok」不代表数据没问题，只代表它们没在那批脏行上崩。

MIT License.
