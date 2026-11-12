# filing-lens

用自然语言查美股公开文件（10-K / 10-Q / 8-K）——**每个答案都带出处，答不出来就明说答不出来**。

> 对标：Finpilot（西雅图，2026-11-04 $10M Series A，Lobby Capital + Madrona）。它做投研问答，我们做同一件事的最小可验证内核，并且把「不许幻觉」写成代码契约而不是提示词。

## 这个项目真正的难点不是 LLM

投研问答的失败模式，90% 不是「模型不够聪明」，而是这三件：

1. **数字从文本里捞**。文本里的数字是被人抄过的，任何人都可能在括注里写错。所以数字类问题**只走 XBRL 结构化事实**，文本通道一律不许出数字。
2. **答非所问**。检索到了相关段落就往上套，用户问 A 你答 B。所以用查询词覆盖率做闸门，覆盖率低于 0.34 直接拒答。
3. **无法自证**。给个答案没有页码/段落，用户无法验证，也就无法信任。所以每个 `Chunk` 带 `Item + 段落序号` 的 `ref`，答案必须挂引用。

## 契约（写进测试，不是写进 README 就算）

| 契约 | 落点 |
| --- | --- |
| 没有引用 = 没有答案 | `answer.py:Answerer._excerpt_answer` 返回 `insufficient_evidence` 且 `citations == []` |
| 数字只走 XBRL | `_metric_answer` 优先；`is_numeric_question` 决定该不该走 |
| 出现指标词 ≠ 在问指标 | `is_numeric_question` 排除 `risk/why/customer/how do` 等定性线索 |
| 表格不进文本索引 | `edgar.extract_tables` 单独通道 |
| 段落可定位 | `Chunk.ref = "{doc}#Item {item}¶{para}"` |

## 快速开始

```bash
cd filing-lens
pip install -e .

# 零配置演示（内置一份 Acme Robotics 的假 10-K + 假 XBRL）
python -m filinglens.cli demo

# 真实文件
python -m filinglens.cli index --html aapl-10k.html --facts AAPL-facts.json --db aapl.db
python -m filinglens.cli ask --db aapl.db --facts AAPL-facts.json \
    "supply chain concentration risk" "how much was revenue in fiscal 2025"
python -m filinglens.cli metric revenue --facts AAPL-facts.json

# 抓真实文件（SEC 要求 User-Agent 带联系方式）
export SEC_UA="your-name your@email"
```

## 架构

```
edgar.py    HTML → Item 分段 → 段落 chunk（带 ref）+ 表格单独抽取；EDGAR 抓取
index.py    纯 Python BM25（k1=1.5, b=0.75）+ 覆盖率闸门；支持按 Item 过滤
facts.py    companyfacts JSON → SQLite；指标别名（中英）→ us-gaap 标签；同比
answer.py   双通道答案合成 + 引用 + 拒答
cli.py      index / ask / metric / demo
```

## 演示输出（真实运行结果）

```
Q: supply chain concentration risk lidar supplier
[ok] Supply chain concentration is our most significant operational risk. The lidar
     module is sourced from one supplier, and lead times have ranged from 14 to 40 weeks.
出处：[1] (text) ACME-10K#Item 1a¶1

Q: revenue
[ok] revenue：FY2025 为 175.0M USD；同比变化 FY2024 +30.0%、FY2025 +34.6%。
出处：[1..3] (xbrl) XBRL:RevenueFromContractWithCustomerExcludingAssessedTax@FY2023-2025

Q: what is the cryptocurrency mining plan in Argentina
[insufficient_evidence] 文件里没有足够证据回答这个问题（证据不足，不作答）。
```

## 为什么不用向量库做第一层

财报查询词高度专有（`contract liabilities`、`Item 1A`），词法匹配比稠密向量更准，而且**可回归**——模型/索引一升级就能用测试证明没退化。向量层可以叠在词法层之后当召回扩展，但不能替掉词法层。

## 路线图

- [x] 分段 / chunk / 表格 / BM25 / XBRL / 双通道 / 拒答 / CLI
- [ ] 8-K 事件抽取（并购、指引调整、高管变动）
- [ ] 跨公司对比（同 tag 同期）
- [ ] 多文件会话（10-K + 10-Q + earnings call）
- [ ] 向量召回层 + 混合排序（保持词法为主）

## 已知局限

- BM25 不理解同义词（`revenue` vs `net sales`），需要查询扩展词表。
- 表格只抽成二维数组，还没做「行列语义识别」（哪列是年份、哪行是指标）。
- 拒答阈值 0.34 是经验值，不同长度的问题需要按 token 数归一。

MIT License.
