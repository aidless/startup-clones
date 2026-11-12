# audit-loop

给中小会计师事务所的**审计底稿自动化内核**：银行余额调节、应收账龄、收入截止测试、重复付款检测 —— 输出例外清单 + 可直接归档的 Excel 底稿。

> 对标：Clark（纽约，2026-11-02 $11M 种子，Touring Capital 领投，累计 $16M）。它卖「自主 AI 审计员」给 CPA 事务所。这里做它的可验证内核，并且把「哪一步该由人判断」写死在代码里。

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
cli.py        run / demo
```

## 路线图

- [x] 三个核心程序 + 重复付款 + 数据完整性 + 底稿导出
- [ ] 函证匹配（银行/往来对账单 PDF → 结构化）
- [ ] 抽样引擎（PPS / 分层随机，含可复现随机种子）
- [ ] 上期底稿对比（哪些例外已整改、哪些重犯）
- [ ] 调整分录生成（例外 → 建议分录，人来签字）

## 已知局限

- 覆盖率是「程序跑了没」，不是「风险覆盖了没」——后者需要风险评估输入，本版本没有。
- 账龄按到期日算，遇到「分期收款/部分回款」需要先做核销匹配，当前会把已部分回款的发票算成全额在账。
- 不做重要性水平判断：例外一律列出，是否调整由会计师决定（这是刻意的，也是产品边界）。

MIT License.
