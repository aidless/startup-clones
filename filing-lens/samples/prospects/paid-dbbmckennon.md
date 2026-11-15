# PAID INC · FY10-K 复核差异表（草案，非审计意见）

- 文件：`0001017655` 期间 `2025-12-31`
- 检查项：6 项固定；本次命中 9 条，未覆盖 3 项
- 每条都可追到段落 ref 或 XBRL 标签；追不到的写在「未覆盖」里，不猜。

| # | 检查 | 我们看到的 | 出处 | 建议动作 | 级别 |
|---|---|---|---|---|---|
| 1 | 现金流量口径 | 两个科目都在：经营现金流 FY2025 = -53,171 USD（期间流量），现金及等价物 FY2025 = 1.1M USD（期末存量） | `XBRL:NetCashProvidedByUsedInOperatingActivities@2025 / XBRL:CashAndCashEquivalentsAtCarryingValue@2025` | 正文若用「cash flow」「cash generated」指前者，注意别被后者的标签带偏 | look |
| 2 | 同比口径 | 经营现金流 2024 = 447,643 USD、2025 = -53,171 USD：基数跨零（由正转负），百分比变化无含义，只能看绝对额 | `XBRL:NetCashProvidedByUsedInOperatingActivities@2024→@2025` | 核对正文是怎么描述这次变化的（通常写「转为净流出」而不是百分比） | look |
| 3 | 同比口径 | 营业收入 2024 → 2025：+11.4%（18.6M USD → 20.7M USD） | `XBRL:RevenueFromContractWithCustomerExcludingAssessedTax@2024→@2025` | 与正文披露的百分比核对一次 | info |
| 4 | 分部加总 | facts 里有 segment 相关标签：NumberOfReportableSegments | `XBRL:segment` | 需人工按分部取值相加后与合计比对 | info |
| 5 | 正文与 XBRL | 营业收入 FY2025：XBRL = 20.7M USD；正文 1 个段落里出现同量级数字（0 个与 XBRL 精确相等），样例 $20,677,832 | `0001017655_10k_2025-12-31#Item 7¶49` | 抽查这几个段落的措辞（approximately / 精确值）与 XBRL 口径是否一致 | info |
| 6 | 正文百分比 | 正文称「increased $2,122,710 or 11%」，XBRL 实算 +11.4% —— 一致 | `0001017655_10k_2025-12-31#Item 7¶47` | 无需动作；此条用于证明核对覆盖到了这一处 | info |
| 7 | 风险因素年度差异 | 上年 2024-12-31 71 段、本年 2025-12-31 72 段；新增/改写 11 段、删除/改写 10 段（段落级文本比对，不做语义判断） | `Item 1A 2024-12-31 → 2025-12-31` | 逐年核对新增/改写的风险条目是否与 MD&A 的表述冲突 | info |
| 8 | 风险因素年度差异 | 新增/改写的段落：「To address these risks, we must, among other things, successfully market our e-commerce products, our merchant payment p…」 | `Item 1A 2024-12-31 → 2025-12-31` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |
| 9 | 风险因素年度差异 | 新增/改写的段落：「We require substantial working capital to fund our business. If we are unable to obtain additional financing in the amou…」 | `Item 1A 2024-12-31 → 2025-12-31` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |

## 未覆盖（照实说，不给结论）
- **正文与 XBRL（净利润）**：正文没有与 XBRL 值 -368,243 USD 同量级的表述
- **正文百分比（经营现金流）**：2024→2025 基数跨零（447,643 USD → -53,171 USD），百分比不可比，本项不做比对
- **员工数**：本份 10-K 未出现含 employees/faculty/staff 的人数句式

## 方法与边界
- 只读公开 EDGAR 文件与 XBRL companyfacts，不接触底稿、不需要系统权限。
- `mismatch` = 正文与数据口径对不上；`look` = 值得人工看一眼；`info` = 供核对的事实。
- 不出审计意见、不判断重要性；四舍五入与口径差异不作为错误结论。
