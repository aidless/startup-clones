# audit-loop

给中小会计师事务所的**审计底稿自动化内核**：银行余额调节、应收账龄、收入截止测试、重复付款检测，
输出例外清单 + 可直接归档的 Excel 底稿。它不替你下审计结论，只把重复的比对做成确定性代码，
把「需要人判断的那几条」列清楚 —— 每一条例外都带审计认定、业务主键和一句可复核的理由。

## 安装

```bash
pip install -e .            # 只依赖 openpyxl
```

## 快速开始：Excel 工作流（十分钟跑出第一份结果）

审计师手上是 Excel，不是 JSON。整条链路只用到三条命令：

```bash
# 1. 生成填空模板（默认写到 out/init/facts.xlsx，--dir 可换目录）
auditloop init

# 2. 在 Excel 里打开 facts.xlsx，把四个示例行换成自家四个年度的数
#    sheet「年度数据」，表头：年度 / 营业收入 / 应收账款 / 毛利 / 经营活动现金流
#    单位：元；某年没有的数留空（空 ≠ 0），年度必须是数字

# 3. 跑分析性程序（按后缀自动认 .xlsx / .json）
auditloop analytics --facts out/init/facts.xlsx

# 4. 跑六项审计程序，输出三页 Excel 底稿
auditloop run --entity "某制造有限公司" --out out/workpaper.xlsx
```

`auditloop analytics` 的退出码：

| 码 | 含义 |
| ---: | --- |
| 0 | 跑完，至少一条指标判定成立且无异常 |
| 1 | 跑完，有异常 |
| 2 | 没跑成：文件缺失、表头认不出、年度非数字 |
| 3 | 跑完了，但一条指标都没判定成（只有一个财年，或应收/毛利/现金流全缺）；stderr 印「未判定 N 项 / 共 M 项」 |

第 3 档是刻意与 0 分开的：`0` 的含义是「查过了，没问题」，全部算不出来时必须能被流水线认出来。

分析性程序也接受 JSON，形状与 Excel 读回来的一致：

```json
{"entity": "Acme Industrial",
 "years": {"2023": {"revenue": 1000.0, "receivables": 100.0,
                    "gross_profit": 400.0, "cfo": 250.0}}}
```

## 六项审计程序（判据各一句）

| 程序 | 认定 | 判据 |
| --- | --- | --- |
| `bank_recon` 银行余额调节 | 存在性 / 完整性 | 按金额 + 3 天日期窗口做 1:1 匹配，金额相同但超窗记「未达账项」，只对现金类科目做（大小写不敏感匹配 `银行存款/现金/cash/bank`）。 |
| `ar_aging` 应收账龄 | 计价与分摊 | 按到期日算逾期天数，`>90` 天且有发票时汇总成一条例外，提示评估坏账准备；缺到期日的发票单列一桶。 |
| `revenue_cutoff` 收入截止 | 截止 | 已确认收入但发货日晚于期末（`tolerance_days` 默认 0，期末当天不算例外），或本期确认收入却无发货记录，即截止例外。 |
| `duplicate_payment` 重复付款 | 存在性 | 同一供应商、同一金额、5 天内出现两笔付款（`amount < 0` 且填了 vendor），即疑重复付款。 |
| `ar_sanity` 应收异常 | 计价与分摊 | 发票金额 ≤ 0 一律列出，金额异常本身就是数据完整性问题。 |
| `ar_completeness` 应收完整性 | 完整性 | 到期日缺失（算不出账龄）或到期日早于开票日（账龄不可靠），两种分开写。 |

## 分析性程序（三条比率/趋势）

抽查凭证能抓错账，抓不到「账本身在讲故事」。这三条判断的是比率与趋势是否自相矛盾：

| 程序 | 触发条件 |
| --- | --- |
| `revenue_vs_receivables` | 应收增速 − 收入增速 > 20pt（渠道压货 / 提前确认收入）；差 > 40pt 记 high |
| `gross_margin_trend` | 毛利率同比变动 > 3pt（成本归集或分类口径被改动） |
| `cash_conversion` | 经营现金流/收入 下滑 > 10pt 或相对下滑 > 25%（利润没变成现金） |

## 演示输出（真实运行）

```
# 审计执行摘要 · Acme Industrial

- 期末：2026-09-30
- 结论：**attention_required**（high 例外 3 条）

| 程序 | 认定 | 状态 | 例外 |
| --- | --- | --- | ---: |
| bank_recon | 存在性 | ok | 4 |
| ar_aging | 计价与分摊 | ok | 1 |
| revenue_cutoff | 截止 | ok | 2 |
| duplicate_payment | 存在性 | ok | 1 |
| ar_sanity | 计价与分摊 | ok | 1 |
| ar_completeness | 完整性 | ok | 1 |
```

例外清单（节选，`auditloop demo` 的完整输出另含 medium/low 7 条）：

| 程序 | 认定 | 严重度 | 对象 | 说明 |
| --- | --- | --- | --- | --- |
| duplicate_payment | 存在性 | high | G3/G6 | Northwind 在 2026-09-20 与 2026-09-21 各付 800.00，疑似重复付款 |
| revenue_cutoff | 截止 | high | INV-1003 | Cobalt Labs 收入确认日 2026-09-30 早于发货日 2026-10-05，期末 2026-09-30 前未发货却确认收入 |
| revenue_cutoff | 截止 | high | INV-1004 | Dunmore 已确认收入但无发货记录（期末 2026-09-30） |

## 核心纪律（每一条都有测试兜底）

| 纪律 | 为什么 | 落点 |
| --- | --- | --- |
| 每个程序必须挂一个审计认定 | 复核人先看「截止测试做了没」，不是「跑了几个脚本」 | `models.py` 六个认定常量 |
| 单步失败不终止整轮 | 现场数据永远有脏行；报错就停会被当成软件坏了 | `engine.py` try/except → `status=error` + `ref=ENGINE` 例外 |
| 只调节现金类科目 | 拿管理费用去碰银行流水会造出一堆假例外 | `checks.reconcile_bank(accounts=...)` |
| 调节差额必须能手工验算 | 底稿要能被第三方重算 | `ReconResult.difference` |
| 空单元格是「缺失」不是 0 | 补 0 会让毛利率、现金含量算出凭空成立的结论 | `excel.read_facts` |
| 底稿三页固定 | 摘要给合伙人 / 例外给现场 / 明细给复核 | `workpaper.py` |

## 架构

```
excel.py      年度数据模板写出 / 读回（.xlsx 与 .json 同构）
models.py     Entry / BankLine / Invoice / Finding / StepResult + 六个审计认定
checks.py     reconcile_bank / ar_aging / revenue_cutoff / duplicate_payments / ...
engine.py     AuditRun：注册程序 → 逐个执行 → 汇总（status / high / coverage）
workpaper.py  openpyxl 三页底稿（摘要 / 例外 / 明细）
fixtures.py   埋了 6 类例外的确定性夹具
cli.py        init / run / analytics / demo
```

## 已知边界

下面每一条都指到实现位置，说的是「什么情况下这份底稿的结论不可信」。

- **只做确定性检查，不做判断。** 全部检查是纯函数、无 IO、无随机（`checks.py:1-5`）；不判重要性水平、不出审计意见、不建议调整分录。`TOL = 0.01`（`checks.py:15`）是金额匹配容差，不是重要性阈值——任何金额的例外都会被列出，是否调整由会计师决定。
- **`status=clean` 不等于没问题。** `AuditRun.status` 只在「无程序报错」且「无 high 例外」时才返回 `clean`（`AuditRun.status`；high 的判定口径见上节 `models.counts_as_high`），medium/low 例外可以同时存在于一份 `clean` 的底稿里；`coverage()` 报的是「程序跑了没」（`engine.py:79-81`），不是「风险覆盖了没」。
- **六类检查各有一组静默跳过条件，没报例外可能是没查。** `reconcile_bank` 只碰科目名里含 `银行存款/现金/cash/bank` 的分录，判断是**大小写不敏感**的子串匹配（`checks.reconcile_bank` 里的 `accounts_cf` 与现金分录筛选，`Bank Account USD`/`CASH-1000` 都能进）；科目名既不含这几个词、又不是真实现金科目的（例如 `其他货币资金`）同样不参与；`duplicate_payments` 只分组 `amount < 0 and vendor` 的分录，没填 vendor 的付款即使同日同额重复也一条例外都不出；`revenue_cutoff` 只处理 `inv.recognized` 为真的发票，未确认收入的发票整条跳过；`ar_aging` 按发票全额、按 `due_date` 算（`checks.py:88-112`），没有回款核销匹配，部分回款的发票仍按全额在账。
- **分析性程序有单独的 CLI 出口，但不在 `run` 的底稿里。** `auditloop run` 仍只注册 6 个程序（`cli.py:build_run`）；三条比率/趋势检查走 `auditloop analytics --facts <Excel 或 JSON> [--json]`（`cli.py:cmd_analytics`），退出码四档见上。输入用 `auditloop init` 生成的 Excel 填，或自己把 ERP/XBRL 导成 `revenue`/`receivables`/`gross_profit`/`cfo`：缺列或某年缺数时那条会印「数据不足」（`analytics.py:54-55,100-101`，`_num` 挡 `None`、`prev==0` 在 `analytics.py:44-48`），不再与「跑了且没问题」共用同一行输出。
- **Excel 输入要求表头与年度可解析。** 表头逐字为 `年度 / 营业收入 / 应收账款 / 毛利 / 经营活动现金流`（`excel.HEADERS`），第一行认不出时直接报错并列出期望表头；年度列必须是数字（容忍 `2023年`、`FY2023`），非数字报错带 Excel 行号；同一财年出现两行直接报错而不是静默取后者。空单元格表示该年没有这一列的数，三条程序会据此报「数据不足」。公式单元格读的是 Excel 保存下来的缓存值（`openpyxl` 的 `data_only`），文件若从未在 Excel 里打开并保存过，`=SUM(...)` 这类格子会被读成空白 —— 需要先保存一次，或直接填数值。
- **期间与日期全是朴素 `date`，无时区、无缺省。** 期末日由调用方传入（`fixtures.PERIOD_END`），`revenue_cutoff` 的 `tolerance_days` 默认 0（`checks.revenue_cutoff(tolerance_days=...)`）：发货日等于期末日不算例外，晚一天就算；带时间戳的导出行必须先归一到同一时区的日历日，否则 23:00 与次日 01:00 会落到相邻两天。`due_date` 为空的发票不进任何逾期桶，单列「无到期日」（`checks.py:95-99`）——算不出账龄就报不出逾期，也不会被默认算成「未到期」。
- **每条例外只带业务主键，不带源文件行号。** `Finding.ref` 是发票号/凭证号（重复付款写成 `G3/G6`，程序自身失败写成 `ENGINE`，`engine.py:49-51`）；底稿「明细」页的「行号」是导出时的顺序号 `enumerate(rows, 1)`（`workpaper.py:78`），源数据筛过行之后它与原始 Excel 行号不再对应，落到「哪个文件哪一行」得靠 ref 回原表查。也只报了这 6 类 + 3 类分析性程序能查的东西：函证、抽样、期后事项、关联方披露都不在范围内（见路线图）。
- **单步失败不会终止整轮，但会让结论降级。** 异常被捕获成 `status=error` 并注入一条 `ref=ENGINE` 的 high 例外（`engine.py:46-53`），整体 `status` 变成 `degraded`（`engine.py:67-68`）；此时「其余程序都 ok」不代表数据没问题，只代表它们没在那批脏行上崩。

## 严重度

`Finding.severity` 的规范值是 `high` / `medium` / `low`。常见变体（`HIGH`、`高`、`严重`、
`Medium`…）在构造时归一成规范值；**认不出来的值原样保留**，但判定上一律**按 high 处理**
（`models.counts_as_high`）。理由：这里判的是「要不要人看一眼」，不是「多严重」——
上游拼错一个词就静默降级，等于让错字替审计师决定「这条例外不重要」。
所以 `status=clean` 只会在「无程序报错」且「无 high 例外、且没有无法识别的严重度」时出现。

## 路线图

- [x] 三个核心程序 + 重复付款 + 数据完整性 + 底稿导出
- [x] Excel 模板进出（`init` / `analytics --facts x.xlsx`）
- [ ] 函证匹配（银行/往来对账单 PDF → 结构化）
- [ ] 抽样引擎（PPS / 分层随机，含可复现随机种子）
- [ ] 上期底稿对比（哪些例外已整改、哪些重犯）
- [ ] 调整分录生成（例外 → 建议分录，人来签字）

## 许可证

MIT，见 [LICENSE](LICENSE)。
