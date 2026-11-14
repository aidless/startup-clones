# 第三轮审查：filing-lens + geo-radar

审查方式：只读源码 + 用项目自带真实数据实跑，不修改两个项目的任何源码或测试，不做任何 git 写操作。
所有命令的工作目录前缀（路径含字面反斜杠，必须两段式）：

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/filing-lens   # 或 startup-clones/geo-radar
```

本次覆盖 commit：`startup-clones` 仓库当前 HEAD（两项目均在该仓库内或子目录；geo-radar 无独立 `.git`）。

---

## 断言清单（README 里可验证的 31 条）

「实测成立?」列只有三种取值：**成立** / **不成立**（=进了下方发现）/ **部分**。

### filing-lens（README.md）

| # | 断言原文（节选） | 实测成立? | 证据命令 |
|---|---|---|---|
| F1 | 每个答案都带出处，答不出来就明说 | 部分 | `python3 -m filinglens.cli ask --html data/0001018724_10k_2025-12-31.htm "研发费用是多少？"` |
| F2 | 数字题 55/55 正确，真值取 XBRL 年度序列最后一年、相对误差≤0.5% | 部分 | `python3 scripts/batch_bench.py --no-fetch`（判据见 P1-1） |
| F3 | 风险因素文本题 20/20 有答案且带段落级出处 | 成立 | 同上，`text 20/20` |
| F4 | 员工数 18/20 给出人数，另 2 家明确拒答 | 部分 | `python3 -m filinglens.cli ask --html data/0000050863_10k_2025-12-27.htm "有多少员工？"` |
| F5 | 该拒答的 40/40 拒答（insufficient_evidence 且引用为空） | 成立 | `python3 scripts/batch_bench.py --no-fetch` |
| F6 | XBRL 未披露项记 n/a 并从分母剔除 | 成立 | 同上，`na_list` 含 5 家 r_and_d |
| F7 | 只接受 https + SEC 域名，单文件 40MB 上限（边读边数） | 成立 | `python3 -c "from filinglens import ingest; ingest._check_url('http://www.sec.gov/x')"` |
| F8 | 落盘名由 tag 决定，`{tag}_10k_{period}.htm` 与 `{tag}_facts.json` 同 tag | 成立 | `python3 -c "from filinglens import ingest; ingest.safe_component('../x','tag')"` |
| F9 | 数字类问题只走 XBRL，文本通道一律不许出数字 | 不成立 | `python3 -m filinglens.cli demo`（Q4 输出 48%） |
| F10 | 覆盖率低于 0.45 直接拒答 | 成立 | `python3 -c "from filinglens.answer import MIN_COVERAGE; print(MIN_COVERAGE)"` → 0.45，且 `negotiation strategy` 类问题被拒 |
| F11 | 每 Chunk 带 `{doc}#Item {item}¶{para}` ref，答案必须挂引用 | 成立 | `python3 -m filinglens.cli index --html data/0000320193_10k_2026-09-26.htm` 观察 ref |
| F12 | 目录页整段丢弃（`_is_toc_gap`） | 成立 | 微软 L2 实测 23 段且无目录页噪声 |
| F13 | 同一 Item 的片段「只留正文最长的那一份」（问题表 L106） / 「够长的全部合并」（失败故事#1 L37） | 部分（README 自相矛盾，代码=后者） | `sed -n '114,149p' filinglens/edgar.py` |
| F14 | 每个 fy 只取「最近申报 + 最新期末」 | 不成立 | `python3 -m filinglens.cli metric revenue --facts data/0000320193_facts.json` |
| F15 | 中文提问靠 66 条词表桥接 | 成立 | `python3 -c "from filinglens import glossary; print(len(glossary.CONCEPTS))"` |
| F16 | 泛词 IDF 加权，apple 在 Apple 10-K 覆盖率 0.43 → 拒答 | 成立 | `python3 -c "...index.coverage('apple iphone warranty')"` |
| F17 | real_regression 8/8 | 成立 | `python3 scripts/real_regression.py` |
| F18 | 微软 FY2026：8.4MB / 营收 $331.84B / 净利 $133.75B / 23 段 / 87 表 | 成立 | `python3 -m filinglens.cli index --html data/0000789019_10k_2026-06-30.htm` |
| F19 | `python3 -m filinglens.cli demo` 三段输出 | 部分 | `python3 -m filinglens.cli demo`（实际 4 个 Q） |
| F20 | 演示服务 `python3 app/server.py --port 8792` 暴露三个接口 | 成立 | `python3 app/server.py --port 8792` + `curl :8792/api/meta` |
| F21 | 覆盖率两道口径：概念级「该组词至少一半出现」 | 不成立 | `python3 -c "...coverage(...,groups=[['supply','chain','suppliers','manufacturing']])"` |
| F22 | 中文提问无词表概念命中则拒答 | 成立 | `python3 -m filinglens.cli ask ... "capital expenditure 是多少"` |
| F23 | 表格不进文本索引 | 成立 | 微软 87 表 / coverage 不含表文本（`edgar.extract_tables` 与 `chunk_sections` 分离） |
| F24 | 失败故事#5：Qualcomm、Intel「它们的 10-K 里真的没有这句」 | 不成立 | `grep -c "85,100" data/0000050863_10k_2025-12-27.htm` |

### geo-radar（README.md）

| # | 断言原文（节选） | 实测成立? | 证据命令 |
|---|---|---|---|
| G1 | 提及次数 = 回答正文中该品牌按词边界匹配后的出现次数 | 成立 | `python3 -c "...extract.find_mentions('Acme '*5+'.', ['Acme'])"` → 1 条 |
| G2 | 出现率分母 = 提示词总条数 | 成立 | `view.load_view(...).prompts_total` → 12 |
| G3 | SoV = 该品牌提及数 / 全部品牌提及数 | 成立 | 12×3 run：25/72=34.7% |
| G4 | 平均位次 = 被提及时的平均出现次序 | 成立 | 同上 1.52 |
| G5 | 引用份额 = 域名引用次数 / 全部引用次数 | 成立（合计 1.0008，舍入） | `metrics.citation_share(...)` |
| G6 | 单次调用不可信，`--repeat` 默认跑 3–5 次 | 成立 | `cli.py:150` `default=3` |
| G7 | `python -m georadar.cli demo` 零配置可跑 | 不成立 | `PYTHONPATH=. python3 -m georadar.cli demo` → exit 1 |
| G8 | `run ... --provider mock` 落库并出报表 | 成立 | 12×3=36 回答 / 72 mentions |
| G9 | 提示词绝不包含目标品牌名 | 成立 | `grep -n "brand" georadar/prompts.py` 无插入点 |
| G10 | 抽取不用 LLM（纯规则） | 成立 | `georadar/extract.py` 全文件无网络/模型调用 |
| G11 | 原始回答必须落库 | 成立 | `sqlite3 /tmp/r3/geo2.db "select count(*) from answers"` → 36 |
| G12 | 「`--provider ollama` 未接线 / CLI 的 choices 里没这个值」 | 不成立 | `grep -n "choices=" georadar/cli.py` |
| G13 | 复跑用 `--provider=magpie`，`data/geo_real_<provider>.json` 保留原始回答 | 部分 | `data/geo_real_magpie.json` 存在，但 CLI 不接受 `magpie` |
| G14 | 「领先/落后/持平」三支（`report.py:71-90`） | 部分 | 三支存在，但非 gap_sov 维度符号错（P0-4） |
| G15 | 情感 = (pos−neg)/(pos+neg)，窗口前 96 后 48 字 | 成立 | `"this is not the best tool"` → +1.0（已知边界已自认） |
| G16 | 品牌匹配大小写不敏感 + 词边界，无别名表 | 成立 | `"Bill.com is fine. Bill Gates also uses it."` → `[('Bill.com',1),('Bill',2)]` |
| G17 | 未提及品牌不进表，avg_position 零提及为 0.0 | 成立（但 0.0 语义误导，P2-3） | `BrandStats(brand='Ghost',mentions=0,...).avg_position` → 0.0 |
| G18 | `run` 与 `report --run-id` 同口径、报表逐字节相等 | 成立 | md5 均为 `aecd032690676eb9c6cb044c318ef980` |
| G19 | MockProvider 品牌顺序按哈希打散，run_index 进种子 | 成立 | `providers.py:58` `seed*100003+h+run_index*7919` |

---

## 发现（按严重度）

### P0-1 filing-lens：员工数「明确拒答」是假的，且拒答文案对用户说了假话

- 位置：`filinglens/answer.py:300`、`filinglens/answer.py:361`（文案）；`filinglens/answer.py:99-102`（`HEADCOUNT_RE` 词表）；README.md:40-41、README.md:174（断言「它们的 10-K 里没有这种陈述」）
- 复现：

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/filing-lens
python3 -m filinglens.cli ask --html data/0000050863_10k_2025-12-27.htm "有多少员工？"
# [insufficient_evidence] ...（全文没有「N 名员工」这类陈述，无法给出人数）
grep -o "comprised of 85,100" data/0000050863_10k_2025-12-27.htm
# comprised of 85,100
```

原文（Intel 10-K，`data/0000050863_10k_2025-12-27.htm`）：

```
We invest in our highly skilled workforce, which was comprised of 85,100
1

people as of December 27, 2025
```

Qualcomm（`data/0000804328_10k_2026-09-27.htm`）：

```
At September 27, 2026, we had approxima
tely 57,000 full-time, part-time and temporary workers
```

把脚注上标摘掉（其余数据一字不改）后同一 Answerer 立刻答出：

```bash
python3 -c "
from filinglens import corpus, edgar, answer
f=corpus.load('data','0000050863'); s=f.sections[0]
t=s.text.replace('85,100\n1\n\npeople','85,100 people')
c=edgar.chunk_sections('0000050863_10k_2025-12-27',[edgar.Section(item=s.item,title=s.title,text=t)])
r=answer.Answerer(c,f.conn).ask('有多少员工？'); print(r.status, r.text[:70])"
# ok We invest in our highly skilled workforce, which was comprised of 85,100 people as of Dece
```

Qualcomm 是词表缺口，与换行无关：

```bash
python3 -c "
from filinglens.answer import HEADCOUNT_RE as R
print(bool(R.search('57,000 full-time, part-time and temporary workers')))
print(bool(R.search('57,000 full-time employees')))"
# False
# True
```

- 为什么是缺陷：数据里两家都写了人数，代码却报「全文没有这类陈述」。用户看到的是**一句关于文件内容的假陈述**，而不是「我没匹配到」，这比单纯拒答更有害；README 也把这个解析缺陷写成了数据事实（L174）。维持在 18/20 的基准分数，是因为判分只看「拒答了没有」，不看「拒答的理由是否成立」。
- 建议修法：`edgar.html_to_text` 丢弃夹在数字与单位之间的孤立短行（`^\d{1,2}$` 且前后都是换行）；`HEADCOUNT_RE` 补 `workers|staff|headcount`；拒答文案改成「正文未匹配到「N + 人数单位」句式」，不要断言文件里没有。

### P0-2 filing-lens：`metric` 的历史年度取到季度值，还输出 +465.4% 这种同比

- 位置：`filinglens/facts.py:115-139`（`annual_series`：`WHERE tag=? AND fp='FY'`，每个 fy 取 `(filed,end)` 最大）
- 复现：

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/filing-lens
python3 -m filinglens.cli metric revenue --facts data/0000320193_facts.json
# FY2019  64.04B USD
# FY2020  64.70B USD
# FY2021 365.82B USD
# 同比 FY2021 +465.4%
```

Apple 10-K 里 FY2019 营收真值 260,174M、FY2020 274,515M。原始 facts 行（同一 tag，`fp='FY'`）：

```
fy=2019 end 2017-09-30 val 229,234,000,000
fy=2019 end 2019-09-28 val 260,174,000,000
fy=2019 end 2019-06-29 val  64,040,000,000   <- 被 annual_series 选中（end 最大）
```

- 为什么是缺陷：companyfacts 的 `fy` 是**申报年度**，一份 10-K 里并列三个财年都记成 `fy=<申报年>`；`max(end)` 于是挑到该申报年内的**季度 frame**。输出格式完全正常（两位小数 + B），没有任何迹象表明它在报一个季度值，而 `+465.4%` 这种数字会直接被下游引用。
- 建议修法：按事实自身财年聚合（用 `end` 的财年 + `frame` 字段，或过滤 `(end - start)` ≈ 365 天的年度 frame），不要用申报年 `fy` 做分组键。
- 附带：`cli ask --html data/0000320193_10k_2026-09-26.htm --facts ... "2026 财年营收是多少"` 给 478.83B 是正确的——最新一年恰好只被最新一份申报覆盖，所以这个 bug 只在「问历史年」时露头，更容易漏。

### P0-3 filing-lens：XBRL 未披露研发时，中文提问返回离题干段落且标 ok

- 位置：`filinglens/answer.py:388`（`return text if text.status == "ok" else (metric or text)`）
- 复现：

```bash
python3 -m filinglens.cli ask --html data/0001018724_10k_2025-12-31.htm "研发费用是多少？"
# [ok] ... 与 IPR&D 会计政策相关的段落 ...
# 出处: 0001018724_10k_2025-12-31#Item 8¶869
python3 -m filinglens.cli ask --html data/0001018724_10k_2025-12-31.htm "r&d expense"
# [no_data] 文件里没有 r&d 的年度数据（XBRL 未披露）。
```

Walmart（`data/0000104169_10k_2026-01-31.htm`）同问 → `[ok]`，正文是 OBBB Act 税务段，cite `#Item 1a¶144`。

- 为什么是缺陷：同一个问题，英文路径诚实说「未披露」，中文路径给出一段讲 IPR&D 会计政策的文字并标 `ok`。这正是 README「答不出来就明说」和契约表「数字只走 XBRL」要防的情形。中文走了 `_excerpt_answer`（因为 CJK 概念命中「研发」但 `wants_ratio`/metric 分支未命中），而最后的 `text if ok` 让文本结果优先级高于 metric 的 `no_data`。
- 建议修法：`ask` 里 `metric.status == "no_data"` 时不要被文本结果覆盖；或对 `has_quantity`/指标类问题要求文本答案必须命中量词句（`has_quantity`）才放行。

### P0-4 geo-radar：差距句的符号和判定方向错，真实 run 里就出现了

- 位置：`georadar/report.py:76-92`（三支措辞）；`georadar/metrics.py:84-98`（`gap_report`）
- 复现（真实 run，`--brand Acme --competitors "Traversal,Rootly,Zeta"`）：

```
落后 **Traversal** 声量 **0.0%**、出现率少 **-1** 条提示词、平均位次差 **-0.21** 位。
```
（Acme 出现率 100%、Traversal 91.7%——是我们多 1 条，却写成「少 -1 条」；声量差距 0.0% 却判「落后」）

合成三例直接暴露：

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/geo-radar
PYTHONPATH=. python3 -c "
from georadar import metrics, report
def show(om,op,opos,rm,rp,rpos):
    st={'Acme':metrics.BrandStats(brand='Acme',mentions=om,prompts_seen=op,positions=[opos]*om),
        'Rival':metrics.BrandStats(brand='Rival',mentions=rm,prompts_seen=rp,positions=[rpos]*rm)}
    for s in st.values(): s._total_mentions=om+rm
    o=report.markdown_report('Acme','AI SRE',['Rival'],st,[],[],10)
    print(o.split('## 2. 差距')[1].split('## 3.')[0].strip())
show(10,10,1.0,10,6,3.0); show(12,10,1.2,10,10,2.0)"
# 落后 **Rival** 声量 **0.0%**、出现率少 **-4** 条提示词、平均位次差 **2.0** 位。
# 领先 **Rival** 声量 **9.1%**、出现率多 **0** 条提示词、平均位次领先 **-0.8** 位。
```

- 为什么是缺陷：第二例里我们平均位次 1.2 优于 2.0，文案写「平均位次领先 **-0.8** 位」——「领先」和负号同时出现，读者无法判断方向；`gap_visibility`/`gap_position` 的符号在落后支不取负（`:90-91`）、在领先支无条件取负（`:84-85`），只有 `gap_sov` 一个开关决定三句话的措辞。第四例（真实 run）里三句话全是反的。表里的数字都对，只有结论句错，最容易被当成结论抄走。
- 建议修法：三个维度各自判方向（`>0 落后 / <0 领先 / =0 持平`）分别措辞，或直接输出带符号的差值列而不要在句子里下「领先/落后」的判断。

### P1-1 geo-radar：README 快速开始第一条命令就崩，且崩之前已经落库

- 位置：`georadar/cli.py:77`（`if args.json:`）、`georadar/cli.py:111-124`（`cmd_demo` 手搓 Namespace 缺 `json`/`out` 字段）
- 复现：

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/geo-radar
PYTHONPATH=. python3 -m georadar.cli demo; echo "exit=$?"
# AttributeError: 'Namespace' object has no attribute 'json'
# exit=1
```

崩之前 `cli.py:71` 已经 `save_run`，`georadar.db` 里留下了 demo run（副作用发生在报错之前）。

- 为什么是缺陷：README 说「零配置可跑」的第一条命令直接 traceback；且用户重跑会累积重复 run，`report` 里出现多条同名 demo。
- 建议修法：`cmd_demo` 用 `parser.parse_args(['demo'])` 拿到全默认值，或给 Namespace 补齐与 argparse 一致的字段。

### P1-2 filing-lens：文本通道会输出数字，与「文本通道一律不许出数字」相反

- 位置：`filinglens/answer.py:308-375`（`_excerpt_answer`）；README.md:57-58
- 复现：

```bash
python3 -m filinglens.cli demo
# [ok] Our top five customers accounted for 48% of revenue in fiscal 2025.
# 出处: ACME-10K#Item 1a¶2
```

- 为什么是缺陷：48% 是文本段落里的数字，直接被当作答案给出，与「数字类问题只走 XBRL，文本通道一律不许出数字」的承诺冲突。判分集里数字题都走 metric 分支，所以基准看不见这条。
- 建议修法：`_excerpt_answer` 在 `has_quantity(question)` 为真且文本答案不含可选出处数字时降级为 `insufficient_evidence`，或在渲染时标注「该数字来自正文，非 XBRL」。

### P1-3 filing-lens：概念覆盖率「至少一半出现」与代码「命中一个就够」矛盾

- 位置：`filinglens/index.py:107-144`（有 groups 时组内任一词命中即整组算命中）；README.md:205-207；代码注释 `filinglens/index.py:116-118` 自己写着「早先要求过半，实测把 9/20 家…改成命中一个就够」
- 复现：

```bash
python3 -c "
from filinglens import corpus, index
f=corpus.load('data','0000320193')
c=[x for x in f.chunks if x.ref.endswith('#Item 1a¶8')][0]
print(c.ref, '|', index.BM25Index(coverage_log := []).coverage(c.text,'supply chain',groups=[['supply','chain','suppliers','manufacturing']]))"
# 0000320193_10k_2026-09-26#Item 1a¶8 | 1.0
```

该 chunk 只含 `suppliers` 一个词，按 README 的「过半」口径应为 0.25。

- 为什么是缺陷：覆盖率是一个**会被拿来解释「为什么拒答/为什么不拒答」的数字**，两套定义相差 4 倍，README 的「演示服务」节按错的口径向用户承诺行为。
- 建议修法：把 README 该段改成「组内任一词命中即算该概念命中」，或把代码改成过半并重跑 20 家看拒答率。

### P1-4 filing-lens：55/55 数字题基准与实现同源，结构上验不出取错行

- 位置：`scripts/batch_bench.py:89-90`（`def truth(conn, metric)` 调用 `F.annual_series`）；`filinglens/answer.py:237-264`（`_metric_answer` 同样调用 `F.annual_series`）
- 复现：

```bash
grep -n "annual_series" scripts/batch_bench.py filinglens/answer.py
# scripts/batch_bench.py:90:    series = F.annual_series(conn, metric)
# filinglens/answer.py:241:        series = F.annual_series(self.conn, metric)
python3 scripts/batch_bench.py --no-fetch   # numeric 55/55
```

- 为什么是缺陷：真值和答案出自同一个函数，报出的「相对误差 0.0%」是格式化往返，不是与 XBRL 原始值的比对；这正是 P0-2 能长期存在的原因（真值也一起错）。**55/55 不是能力证据。**
- 建议修法：判据改用原始 `companyfacts` 中 `frame` 为年度、`end` 落在该财报期的行，独立于 `annual_series`。

### P2-1 filing-lens：README 演示输出块与实际输出漂移

- 位置：README.md:150-166
- 复现：`python3 -m filinglens.cli demo`
- 实际：README 只列 3 个 Q，实际输出 4 个；`revenue` 行 README 写「同比变化 … 出处：[1..3]」，实际是「近三年同比 FY2024 +30.0%、FY2025 +34.6%」+ 三行独立 `[1][2][3]`。
- 建议修法：重新生成该块，或加断言测试比对 README 与实跑输出。

### P2-2 geo-radar：README 表格「ollama 未接线 / choices 里没这个值」是假陈述，反过来 magpie 才是没接的

- 位置：README.md:121；`georadar/cli.py:137-139`；`georadar/providers.py:152-168`
- 复现：

```bash
grep -n "choices=" georadar/cli.py
# 137: choices=["mock","ollama","openai","openai-compat","deepseek","kimi","vllm"],
python3 -m georadar.cli run --provider magpie ...   # argparse: invalid choice: 'magpie'
```

`build_provider` 支持 `magpie`（`providers.py:152-168`），`scripts/real_geo.py:100` 也用它复跑出 `data/geo_real_magpie.json`，但 CLI 不认——README L128/L160 让人用 `--provider=magpie` 复跑，走的其实是脚本而不是 CLI。
- 建议修法：choices 补 `magpie`，删掉「ollama 未接线」那行。

### P2-3 geo-radar：百分点被印成百分比

- 位置：`georadar/report.py:89-91`（`_pct(gap['gap_sov'])`）
- 复现：真实报表 `落后 **Rootly** 声量 **1.4%**、出现率少 **1** 条提示词…`（Acme 34.7% vs Rootly 36.1%，差 1.4 个百分点）
- 为什么是缺陷：SoV 的差是百分点，写成 `%` 会被读成「相对低 1.4%」（实际相对低约 4%）。
- 建议修法：差距句用「个百分点 / pp」。

### P2-4 geo-radar：零提及的 avg_position 是 0.0，看起来最好

- 位置：`georadar/metrics.py:31-33`
- 复现：`metrics.BrandStats(brand="Ghost",mentions=0,prompts_seen=0,positions=[]).avg_position` → `0.0`
- 为什么是缺陷：位次越小越好，0.0 比所有真实品牌都「好」；一旦某品牌被提及但只在表外出现，排序/下游计算会把它排到第一。README 虽说「零提及为 0.0」（算已知行为），但这是会骗人的默认值。
- 建议修法：返回 `None` 并在报表里印 `—`。

### P2-5 filing-lens：`--port` 默认值与 README 不一致（README 命令带 `--port 8792`，代码默认 8765）

- 位置：`app/server.py`（`--port` 默认 8765）；README.md:200
- 复现：`python3 app/server.py --help | grep -A1 port`
- 为什么是缺陷：只影响「只读 README、不加参数」的人，命令本身能跑通，故按 P2 记。
- 建议修法：README 里注明默认端口，或代码默认改成一致。

---

## 我核过但**成立**的断言（避免下一轮重复劳动）

| 断言 | 命令 | 输出要点 |
|---|---|---|
| 22 家真实 10-K 全部可解析 | `ls data/*_facts.json \| wc -l` → 22；`ls data/*_10k_*.htm \| wc -l` → 22 | 44 文件，tag 成对 |
| ingest 三重守卫 | `ingest._check_url('http://www.sec.gov/x')` → `IngestError 只接受 https`；`'https://evil.example.com/x'` → `只接受 SEC 域名`；`safe_component('../x','tag')` → `IngestError`；`MAX_BYTES` = 41943040 | 与 README 一致 |
| 微软 FY2026 数字 | 见 F18 | sections 23 / chunks 607 / tables 87 / 331.84B / 133.75B / 35.56B / 223,000 |
| real_regression 8/8 | `python3 scripts/real_regression.py` | 输出块与 README L122-131 逐字一致 |
| 拒答 40/40 | `python3 scripts/batch_bench.py --no-fetch` | 全部 `insufficient_evidence` 且 cites 为空 |
| 中文无概念命中即拒答 | `cli ask ... "capital expenditure 是多少"` | `insufficient_evidence`，文案「问题里的中文没有命中词表里的任何概念」 |
| ref 形态 `{doc}#Item {item}¶{para}` | `cli index` / `ask` 输出 | 如 `0000320193_10k_2026-09-26#Item 1a¶8` |
| geo `run` 与 `report --run-id` 逐字节相等 | `md5sum /tmp/r3/run2.md <(python3 -m georadar.cli report --run-id ...)` | 均为 `aecd032690676eb9c6cb044c318ef980` |
| 同品牌同回答只算 1 条提及 | `find_mentions('Acme '*5, ['Acme'])` | 1 条，position=1 |
| `Bill.com` / `Bill` 分开计 | `find_mentions('Bill.com is fine. Bill Gates also uses it.', ['Bill.com','Bill'])` | `[('Bill.com',1),('Bill',2)]` |
| 词边界 + 大小写不敏感 | `find_mentions('acme ACME Acmes',['Acme'])` | 只命中前两个词位，`Acmes` 不命中 |
| 情感公式与窗口 | `sentiment_of('this is not the best tool','tool')` | `+1.0`（前 96 后 48 字窗口正确截取） |
| bootstrap 固定 seed | `stats.bootstrap_ci(...)` 连跑两次 | 区间完全相同 |
| 原始回答落库 | `sqlite3 /tmp/r3/geo2.db "select count(*) from answers"` | 36（= 12 提示词 × 3 次） |
| 提示词不含品牌名 | `grep -n "brand" georadar/prompts.py` | 仅注释，无模板插值 |

---

## 复核用命令速查

```bash
cd '/home/liuzewen/F:\deepseek' && cd startup-clones/filing-lens
python3 -m filinglens.cli demo                                    # P0-3 前置、P1-2、P2-1
python3 -m filinglens.cli metric revenue --facts data/0000320193_facts.json   # P0-2
python3 -m filinglens.cli ask --html data/0000050863_10k_2025-12-27.htm "有多少员工？"  # P0-1
python3 -m filinglens.cli ask --html data/0001018724_10k_2025-12-31.htm "研发费用是多少？"  # P0-3
python3 scripts/batch_bench.py --no-fetch                         # P1-4
python3 scripts/real_regression.py

cd '/home/liuzewen/F:\deepseek' && cd startup-clones/geo-radar
PYTHONPATH=. python3 -m georadar.cli demo                         # P1-1
PYTHONPATH=. python3 -m georadar.cli run --brand Acme --category "AI SRE" \
  --competitors "Traversal,Rootly,Zeta" --provider mock --repeat 3 --limit 12 \
  --db /tmp/r3/geo3.db --out /tmp/r3/run3.md                      # P0-4 真实证据
PYTHONPATH=. python3 -m georadar.cli report --run-id <id> --db /tmp/r3/geo3.db
```
