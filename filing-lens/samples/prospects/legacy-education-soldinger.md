# LEGACY EDUCATION INC. · FY10-K 复核差异表（草案，非审计意见）

- 文件：`0001836754` 期间 `2026-06-30`
- 检查项：6 项固定；本次命中 10 条，未覆盖 2 项
- 每条都可追到段落 ref 或 XBRL 标签；追不到的写在「未覆盖」里，不猜。

| # | 检查 | 我们看到的 | 出处 | 建议动作 | 级别 |
|---|---|---|---|---|---|
| 1 | 现金流量口径 | 两个科目都在：经营现金流 FY2026 = 4.0M USD（期间流量），现金及等价物 FY2026 = 22.7M USD（期末存量） | `XBRL:NetCashProvidedByUsedInOperatingActivities@2026 / XBRL:CashAndCashEquivalentsAtCarryingValue@2026` | 正文若用「cash flow」「cash generated」指前者，注意别被后者的标签带偏 | look |
| 2 | 同比口径 | 经营现金流 2025 → 2026：-48.2%（7.8M USD → 4.0M USD） | `XBRL:NetCashProvidedByUsedInOperatingActivities@2025→@2026` | 与正文披露的百分比核对一次 | info |
| 3 | 同比口径 | 营业收入 2025 → 2026：+24.8%（64.2M USD → 80.1M USD） | `XBRL:RevenueFromContractWithCustomerExcludingAssessedTax@2025→@2026` | 与正文披露的百分比核对一次 | info |
| 4 | 分部加总 | facts 里有 segment 相关标签：NumberOfReportableSegments | `XBRL:segment` | 需人工按分部取值相加后与合计比对 | info |
| 5 | 正文与 XBRL | 营业收入 FY2026：XBRL = 80.1M USD；正文 1 个段落里出现同量级数字（0 个与 XBRL 精确相等），样例 $80.1 million | `0001836754_10k_2026-06-30#Item 7¶117` | 抽查这几个段落的措辞（approximately / 精确值）与 XBRL 口径是否一致 | info |
| 6 | 正文与 XBRL | 净利润 FY2026：XBRL = 9.1M USD；正文 2 个段落里出现同量级数字（0 个与 XBRL 精确相等），样例 $9.1 million | `0001836754_10k_2026-06-30#Item 7¶127` | 抽查这几个段落的措辞（approximately / 精确值）与 XBRL 口径是否一致 | info |
| 7 | 员工数 | 正文披露 120 名 faculty（不是 employees 口径，核对时注意 FTE/兼职是否分开算） | `0001836754_10k_2026-06-30#Item 1¶206` | 与底稿人数及上年披露核对口径（FTE / 全职 / 兼职） | info |
| 8 | 风险因素年度差异 | 上年 2025-06-30 264 段、本年 2026-06-30 279 段；新增/改写 90 段、删除/改写 75 段（段落级文本比对，不做语义判断） | `Item 1A 2025-06-30 → 2026-06-30` | 逐年核对新增/改写的风险条目是否与 MD&A 的表述冲突 | info |
| 9 | 风险因素年度差异 | 新增/改写的段落：「Our institutions are subject to the educational laws and regulations of the State of California where our physical campu…」 | `Item 1A 2025-06-30 → 2026-06-30` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |
| 10 | 风险因素年度差异 | 新增/改写的段落：「State education laws and regulations may limit our campuses’ ability to operate or to award degrees, diplomas, or certif…」 | `Item 1A 2025-06-30 → 2026-06-30` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |

## 未覆盖（照实说，不给结论）
- **正文百分比（营业收入）**：正文未用百分比表述该指标（XBRL 实算 +24.8%）
- **正文百分比（经营现金流）**：正文未用百分比表述该指标（XBRL 实算 -48.2%）

## 方法与边界
- 只读公开 EDGAR 文件与 XBRL companyfacts，不接触底稿、不需要系统权限。
- `mismatch` = 正文与数据口径对不上；`look` = 值得人工看一眼；`info` = 供核对的事实。
- 不出审计意见、不判断重要性；四舍五入与口径差异不作为错误结论。
