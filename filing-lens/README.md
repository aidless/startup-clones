# filing-lens

用自然语言查美股公开文件（10-K / 10-Q / 8-K）——**每个答案都带出处，答不出来就明说答不出来**。

> 对标：Finpilot（西雅图，2026-11-04 $10M Series A，Lobby Capital + Madrona）。它做投研问答，我们做同一件事的最小可验证内核，并且把「不许幻觉」写成代码契约而不是提示词。


## 20 家真实公司的基准（`bench/report.md`）

> 口径说明：`data/` 里现在有 **22 家**，其中 `0000909832`、`0002078730` 是后来为「复核差异表」演示补进来的小盘样本，**没有纳入这份 20 家基准**（重跑基准见`scripts/batch_bench.py --no-fetch`）。

```bash
python3 scripts/batch_bench.py            # 缺的文件自动下载，约 3–5 分钟
python3 scripts/batch_bench.py --no-fetch # 只用 data/ 里已有的
```

| 题类 | 结果 | 判法 |
|---|---|---|
| XBRL 数字题（营收 / 净利 / 研发） | **55/55 正确** | 真值取 XBRL 年度序列最后一年，答案金额与之比相对误差 ≤0.5% |
| 风险因素（文本题） | **20/20 有答案且带段落级出处** | 只验格式，内容对错机器判不了 |
| 员工数 | **18/20 给出人数**，2 家明确拒答 | 必须给出「N 名员工」的陈述，且双年度并列时要取本期那个数 |
| 该拒答的（CEO 生日 / 门店数） | **40/40 拒答** | 必须 `insufficient_evidence` 且引用为空 |

XBRL 里没披露的项目（Amazon/Adobe/Coca-Cola/Walmart/JPM 没有 R&D 标签）记为 n/a，
**从分母里剔除**——不能把「公司没披露」算成「系统答错」，那是最常见的自我贴金。

### 这份基准自己在 20 家公司上先失败了四次

不是「设计好然后跑通」，是**跑出来才发现设计是错的**：

1. **Microsoft 的正文丢掉 88%**：它的 10-K 每页页眉都印着 `Item 1`，正文被切成 4k 的碎段，
   旧实现「同 Item 只留最长那份」→ 393k 字符只剩 45k。改成「够长的同 Item 片段全部合并」。
2. **Intel 的正文一段都没有**：它的 `Item N` 只出现在文末索引页（23 处全挤在最后 2k 字符），
   按 Item 切出来不到全文的 1%。加了回退：**结构化抽取保留不足 15% 时整篇当一段文本**。
3. **9/20 家的「有多少员工」被判证据不足**：员工那组有五个英文词，正文通常只写 `employees`
   一个，而概念覆盖率要求「组内过半命中」——改成「命中一个就够」。
4. **同一句里两个年份取错**：Coca-Cola 写 `65,900 and 69,700 employees, respectively`，
   贴着 `employees` 的是**旧**数字。加了 `respectively` 的特判，取第一个。
5. **员工数根本没进 top-3**：它常写在第 40 篇里一句话，BM25 按查询词排不进来。改成专门一条路：
   全文扫「N 名员工」的陈述，找到就用它答，找不到就拒答（Qualcomm、Intel 就一直拒答——
   因为它们的 10-K 里真的没有这句）。

## 任意公司 / 任意 URL

```bash
curl -X POST localhost:8765/api/ingest -H 'Content-Type: application/json' -d '{"cik":"320193"}'
curl -X POST localhost:8765/api/ingest -H 'Content-Type: application/json' \
     -d '{"url":"https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl-20260926.htm"}'
```

只接受 https + SEC 域名，单文件 40MB 上限（边读边数，超了立刻停）。
落盘名由 tag 决定，`{tag}_10k_{period}.htm` 与 `{tag}_facts.json` 必须同 tag，否则服务找不到。

## 这个项目真正的难点不是 LLM

投研问答的失败模式，90% 不是「模型不够聪明」，而是这三件：

1. **数字从文本里捞**。文本里的数字是被人抄过的，任何人都可能在括注里写错。所以数字类问题**只走 XBRL 结构化事实**，文本通道一律不许出数字。
2. **答非所问**。检索到了相关段落就往上套，用户问 A 你答 B。所以用查询词覆盖率做闸门，覆盖率低于 0.45（`answer.py:18 MIN_COVERAGE`）直接拒答。
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

## 真实数据上做了哪些事（Apple FY2026 10-K 实测）

夹具跑通只是及格线。接真实文件之后，四类问题立刻暴露，全部已修并锁进回归：

```bash
python scripts/fetch_edgar.py 0000320193        # 拉 Apple 10-K + XBRL（data/ 不入库）
python scripts/real_regression.py               # 8 个问题对真实数字
```

| 问题 | 真实表现 | 修法 |
| --- | --- | --- |
| 目录页 | 解析出 46 个 Section，正文每段只有 1~2 个字符 | `_is_toc_gap`：两个 Item 之间只剩页码 ⇒ 目录页，整段丢弃（`test_toc_page_is_dropped`） |
| 同一 Item 多次命中 | 交叉引用页 / 10-K Summary 索引覆盖正文 | 按 item 归并，只留正文最长的那一份（23 段，Item 1 = 20,838 字符） |
| XBRL 同一财年多行 | 同比出现 `-61.5%` 这种离谱数字（同一 fy 混了不同 `end`） | 每个 fy 只取「最近申报 + 最新期末」那一行（`test_facts` 覆盖） |
| 中文提问零召回 | 供应链/关税问题全部「证据不足」 | `glossary.py` 财务词表扩写 + 覆盖率分母剔除中文单字（`test_coverage_ignores_chinese_characters`） |
| 泛词命中 | 「CEO 生日」被 Apple Arcade 那段答上（覆盖率 0.5） | 覆盖率改 IDF 加权，`apple` 在 Apple 的 10-K 里没有信息量（实测降到 0.43 → 拒答） |
| 「多少」类问题 | 问员工数，答的是研发费用里的 headcount 成本 | 问数量时只在含「量」的句子里选（年份不算量），跨 top-3 段落找 |

真实回归结果（`python scripts/real_regression.py`，8/8）：

```
[PASS] 2026 财年营收是多少？      营收：FY2026 为 478.83B USD；近三年同比 FY2024 +2.0%、FY2025 +6.4%、FY2026 +15.1%
[PASS] 净利润是多少              净利润：FY2026 为 132.18B USD；近三年同比 FY2024 -3.4%、FY2025 +19.5%、FY2026 +18.0%
[PASS] 研发费用是多少            研发：FY2026 为 45.77B USD；近三年同比 FY2024 +4.9%、FY2025 +10.1%、FY2026 +32.5%
[PASS] 公司有多少员工            As of September 26, 2026, the Company had approximately 167,000 full-time equivalent employees.
[PASS] 供应链主要依赖哪些地区    ...a majority of the Company's supplier facilities... are located outside the U.S.
[PASS] 风险因素里提到的关税影响  Beginning in the second quarter of 2025, new tariffs were announced on imports to the U.S., including...
[PASS] Apple 的 CEO 生日是哪天   拒绝作答（覆盖率 0.43 < 0.45）
[PASS] 有多少家门店              拒绝作答（文件里确实没写门店数）
```

微软 FY2026 10-K（8.4 MB）同样跑通：营收 $331.84B、净利 $133.75B、23 段、87 张表。

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

## 已知边界

这一节写的都是**实测撞到的边界**，每条都能在代码或 `data/` 里查到，不是免责声明。

- **中文问句靠一张 66 条的词表桥接，词表外的新说法直接拒答**。英文问句直接进 BM25 词法检索；
  中文问句先由 `glossary.py:11-80` 把词条扩成英文词组（供应链 → `supply chain suppliers manufacturing`），
  再检索。词表里没有的说法（实测：`分拆上市计划`、`中试线建设进度`、`股东回报框架`）在英文语料里
  零命中，返回 `insufficient_evidence`——是拒答，不是「沾边就答」。**中英混合也会被这条挡住**：
  只要问句里有中文、而词表概念一个都没命中，即使英文部分本来检索得到也直接拒答
  （`answer.py:325`；实测 `capital expenditure 是多少` 拒答）。
- **员工数是「正文句式」问题，不是数据问题**。人数只从 `数字 + employees/people/associates/...`
  的句子里读（`answer.py:99-102` 的 `HEADCOUNT_RE`，`answer.py:268-305` 全文扫句）。
  所以 `bench/report.md` 里 20 家有 2 家（Intel、Qualcomm）明确拒答——它们的 10-K 里没有这种陈述。
  **表格里的人数读不到**：`html_to_text` 把每个单元格拆成独立行（`edgar.py:69-71`），
  「科目名 / 人数」不再构成「数字在前」的句式；而表格通道只抽成二维数组
  （`edgar.py:175`）、答案器只拿到 `chunks`（`corpus.py:35`），不参与人数回答。
- **现金流量科目是一张枚举别名表，不是语义匹配**。`facts.py:38-44` 逐条列了
  `cash flow from operations` / `operating cash flow` / `cash provided by operating activities` /
  `经营现金流` 等写法。表外说法认不出指标（`facts.py:103-112`），实测 `capital expenditure 是多少`
  返回 `resolve_metric → None`；更短的别名还会抢先命中，实测 `现金流是多少` 命中的是 `现金`
  （现金余额 FY2026 36.30B），不是经营现金流（145.10B）。
- **每家公司只有 `data/` 里那一份 10-K，做不了跨年度 / 跨申报对比**。`data/` 是 22 个
  `.htm`，一个 CIK 一份；`corpus.load` 只取 glob 命中的最后一份（`corpus.py:74-78`），
  所以「去年那份 10-K 怎么说」没有第二份正文可查。XBRL 侧虽然带多财年序列，但同一 fy
  只保留「最近申报 + 最新期末」一行（`facts.py:115-139`），这是同一份申报历史，不是逐年原文对比。
  跨文件会话 / 跨公司对比都还在路线图里。
- **没有查询改写层，问法差异会改变结果**。检索只有 BM25 词法打分（`index.py:60-86`）加词表扩写，
  不做同义改写，也不判断「这两种问法是不是一个问题」。实测同一份 Apple 10-K：
  `营收是多少` 走 XBRL 答 478.83B（`metric`），`营收增长情况` 却落到文本通道，
  摘了一句「net sales 按产品拆分」的段落（`answer.py:36-42` 的 `is_numeric_question` 只看线索词）；
  `supply chain risk` 与 `供应链风险` 给出的段落也不同。想稳，就用 10-K 里的原词问。
- **表格只到二维数组，没有行列语义**。`extract_tables` 给的是行列字符串（`edgar.py:175`），
  分不出哪列是年份、哪行是指标，所以表格类问题必须走 XBRL，表格本身不参与数字回答。

MIT License.

## 演示服务

```bash
python3 app/server.py --port 8792     # → http://127.0.0.1:8792
```

单页界面 + 三个接口（`/api/filings`、`/api/meta`、`/api/ask`）。页面只做一件事：
把库里已经验证过的链路原样暴露出来——**回答正文、状态徽章、段落级出处**三者同屏。

### 覆盖率的两道口径（真实数据逼出来的）

1. **词级 IDF 覆盖**：分母是查询词的 IDF 加权，用来挡住「只蹭到 CEO 三个字母」的假命中。
2. **概念级覆盖**：中文概念经 `glossary` 桥成一组英文词，一个概念算命中要求该组词至少一半出现。
   纯中文提问时词级分母被同义词撑大（供应链 → supply chain suppliers manufacturing），
   真答案只有 0.434，低于阈值 0.45 会被误杀；概念级能救回来。

两者取较高者，但加一条硬约束：**中文提问必须有词表概念被命中，否则直接拒答**。
没有这条，「CEO 的生日是哪天」的分母只剩 `ceo` 一个词，任何含 CEO 的段落都拿 100% 覆盖率。
