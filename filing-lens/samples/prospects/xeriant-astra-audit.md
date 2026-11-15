# XERIANT, INC. · FY10-K 复核差异表（草案，非审计意见）

- 文件：`0001481504` 期间 `2026-06-30`
- 检查项：6 项固定；本次命中 7 条，未覆盖 2 项
- 每条都可追到段落 ref 或 XBRL 标签；追不到的写在「未覆盖」里，不猜。

| # | 检查 | 我们看到的 | 出处 | 建议动作 | 级别 |
|---|---|---|---|---|---|
| 1 | 现金流量口径 | 两个科目都在：经营现金流 FY2026 = -791,756 USD（期间流量），现金及等价物 FY2026 = 87,594 USD（期末存量） | `XBRL:NetCashProvidedByUsedInOperatingActivities@2026 / XBRL:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents@2026` | 正文若用「cash flow」「cash generated」指前者，注意别被后者的标签带偏 | look |
| 2 | 同比口径 | 经营现金流 2025 = -1.3M USD、2026 = -791,756 USD：都是负数，按绝对值算「变化 +38.6%」，这个百分比没有经济含义 | `XBRL:NetCashProvidedByUsedInOperatingActivities@2025→@2026` | 正文若给出百分比变化，核对它是按绝对值还是按带符号基数算的 | look |
| 3 | 分部加总 | facts 里有 segment 相关标签：NumberOfReportableSegments | `XBRL:segment` | 需人工按分部取值相加后与合计比对 | info |
| 4 | 正文与 XBRL | 净利润 FY2026：XBRL = 392,278 USD；正文 3 个段落里出现同量级数字（3 个与 XBRL 精确相等），样例 $392,278 | `0001481504_10k_2026-06-30#Item 7¶103` | 抽查这几个段落的措辞（approximately / 精确值）与 XBRL 口径是否一致 | info |
| 5 | 风险因素年度差异 | 上年 2025-06-30 148 段、本年 2026-06-30 130 段；新增/改写 29 段、删除/改写 47 段（段落级文本比对，不做语义判断） | `Item 1A 2025-06-30 → 2026-06-30` | 逐年核对新增/改写的风险条目是否与 MD&A 的表述冲突 | info |
| 6 | 风险因素年度差异 | 新增/改写的段落：「Currently, there is no revenue being generated and we have significant operating losses that are expected to continue in…」 | `Item 1A 2025-06-30 → 2026-06-30` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |
| 7 | 风险因素年度差异 | 新增/改写的段落：「The high capital requirements of building materials manufacturing may require us to seek large-scale financing, includin…」 | `Item 1A 2025-06-30 → 2026-06-30` | 确认这条新风险在本年 MD&A 里有没有对应表述 | look |

## 未覆盖（照实说，不给结论）
- **正文百分比（经营现金流）**：正文未用百分比表述该指标（XBRL 实算 +38.6%）
- **员工数**：本份 10-K 未出现含 employees/faculty/staff 的人数句式

## 方法与边界
- 只读公开 EDGAR 文件与 XBRL companyfacts，不接触底稿、不需要系统权限。
- `mismatch` = 正文与数据口径对不上；`look` = 值得人工看一眼；`info` = 供核对的事实。
- 不出审计意见、不判断重要性；四舍五入与口径差异不作为错误结论。
