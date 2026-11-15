# 真实样本：三家小盘事务所客户的 10-K 复核差异表

这三份不是我们自己造的用例，是真客户真文件：**从 EDGAR 抓到原文**，用
`filing-lens/scripts/review_diff.py` 原样跑出，`.md` 与 `.pdf` 一一对应。
发给事务所时直接附 PDF（他们不会点开 markdown）。

## 三份样本

| 文件 | 公司 | CIK | 事务所（PCAOB 注册） | 期间 | 申报日 | accession |
|---|---|---|---|---|---|---|
| `xeriant-astra-audit.{md,pdf}` | XERIANT, INC.（XERI） | 0001481504 | Astra Audit | 2026-06-30 | 2026-09-28 | 0001477932-26-005837 |
| `paid-dbbmckennon.{md,pdf}` | PAID INC（PAYD） | 0001017655 | dbbmckennon | 2025-12-31 | 2026-03-31 | 0001437749-26-010730 |
| `legacy-education-soldinger.{md,pdf}` | Legacy Education Inc.（LGCY） | 0001836754 | L J Soldinger | 2026-06-30 | 2026-09-24 | 0001493152-26-044147 |

每份都同时抓了**上一期 10-K**（`--fetch-prior`，从 EDGAR 现场取），所以「风险因素年度差异」
这一项在三份上都真跑了，不是 skipped：

| 公司 | 上年 → 本年 | Item 1A 段数 | 新增/改写 | 删除/改写 |
|---|---|---|---|---|
| XERIANT | 2025-06-30 → 2026-06-30 | 148 → 130 | 29 | 47 |
| PAID | 2024-12-31 → 2025-12-31 | 71 → 72 | 11 | 10 |
| Legacy | 2025-06-30 → 2026-06-30 | 264 → 279 | 90 | 75 |

XERIANT 上这条检查抓到的第一条新风险就是「Currently, there is no revenue being generated
and we have significant operating losses that are expected to continue」——这类句子正是
复核合伙人要一眼看到的东西，靠人工翻两版 PDF 对照很费时间。

事务所归属取自 SEC 全文检索 `go-to-market/scripts/find_filers.py`（`"<所名>"` 命中 10-K），
不是猜的。原文与 XBRL 存在 `filing-lens/data-prospects/`，**不进 `data/`**——
`data/` 的 22 份是语料矩阵基线的底物，混进小盘文件会让基线的 `min_chunks` 断言失效。

## 复算

```bash
cd startup-clones/filing-lens
python3 scripts/review_diff.py 0001481504 --data data-prospects \
        --out samples/prospects/xeriant-astra-audit.md \
        --pdf samples/prospects/xeriant-astra-audit.pdf
```

## 这三份各自说明了什么

- **PAID INC**：营收 20.7M、正文按**整元**记账（`$ 20,677,832`），是典型小盘写法。
  6 项检查里 5 项出了结论；经营现金流由 +447,643 转 -53,171，报告写「基数跨零、
  百分比无含义」，不拿 -111.9% 去否定正文。
- **Legacy Education**：营收 80.1M、办学公司，人数披露用 `faculty` 而不是 `employees`；
  正文金额与 XBRL 精确对齐（`$80.1 million`、`$9.1 million`），报告给 info 供抽查。
- **XERIANT**：CFO 为负、现金只有 87,594 美元（含受限现金的合并标签）；
  同一份里净利润 392,278 与正文三处精确相等。

## 必须说清的边界

1. **三份都没有 `mismatch`**。大所/正规所审过的文件本来就基本对得上——
   「跑完没抓到大错」是正确结论，不是产品失败。演示「能抓到」请看
   `samples/03-broadcom-injected-defect.*`（人工注入一处真缺陷，检查必须抓到）。
2. **单项未覆盖照实写**：`正文与 XBRL（净利润）` 在 PAID 上未命中同量级表述，就写未命中；
   `正文百分比（经营现金流）` 在 PAID 上因基数跨零（+447,643 → -53,171）拒绝比对。
   补抓上年申报之前，`风险因素年度差异` 也是 skipped——「没法比」与「比过没问题」必须分开写。
3. **段落级 diff 不是语义 diff**：段落按空行切，原文重排/换行变化也会被计入条数，
   所以只用来定位要看哪几段，不做「新增了 N 条风险」的规模结论（报告里 `doubt` 写明）。
4. **不是审计意见**：不出重要性判断、不判错报，只把「正文这句话与数据口径对不上」
   的地方列出来给人看。
5. **PDF 由本机 Chrome 无头打印**（`scripts/render_pdf.py`）。换机器要装
   `google-chrome` 与中文字体（Noto CJK / 文泉驿），否则 `--pdf` 会明确报错退出 2。
