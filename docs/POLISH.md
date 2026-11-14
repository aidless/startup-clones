# 打磨记录（2026-11-13）

「把所有项目打磨好」这句话如果不定义成可判定项，最后只会得到一堆形容词。这里把它固定成
**七项机器检查 + 一条一次跑完全部的命令**，然后按检查报出来的红灯逐项修，并且把修的过程中
顺带发现的真缺陷写成测试。

## 怎么判定「打磨好了」

```bash
cd startup-clones
python3 scripts/polish_audit.py     # 七项硬检查，逐项目打勾
python3 -m pytest                   # 一条命令跑完七个项目的全部测试
```

`polish_audit.py` 的七项：

| 项 | 判据 | 为什么是硬项 |
| --- | --- | --- |
| `readme` | 有「快速开始 / 用法」段，且段内有可复制代码块 | 陌生人拿到仓库，第一个问题就是「怎么跑」 |
| `limits` | 有「已知边界 / 局限 / 限制」段，正文 ≥40 字 | 没有边界的 README 是在暗示「什么都能干」 |
| `pyproject` | 有 `name` + `version` | 能装、能报版本，才有升级与排障的锚 |
| `cli` | `python3 -m <pkg>.cli --help` 退出 0 且输出含 `usage` | 入口跑不通的项目等于不存在 |
| `hygiene` | 裸 `except:`、`TODO/FIXME`、非 CLI 文件的 `print(` 不超标 | 这些是「以后再修」的化石 |
| `numbers`（软） | README 里的数字带单位 | 有数字才谈得上可复算 |
| `tests`（软） | 能 `--tests` 直接跑 pytest | 同上 |

注意 `go-to-market/` 不在七项检查里（它是文档包 + 两个脚本），但它的 5 个测试也在根 `pytest.ini` 的 `testpaths` 里。

## 现在的状态

- 七个项目 **硬项全过**（`7 个项目硬项全过。`）
- `python3 -m pytest` → **331 passed**（打磨完成时；借入外部机制后 351；第二轮为 **396**）
- 这根命令以前跑不起来：`python3 -m pytest` 会把仓库根放进 `sys.path`，而 `cruxline/`（目录）与
  `cruxline/cruxline/`（真包）同名，`import cruxline` 先命中那个没有 `__init__.py` 的目录，
  子项目测试全部 ImportError；同时七个项目各自 `pyproject` 里的 `pythonpath=["."]` 在根目录不生效。
  处理方式写在根 `conftest.py` 的注释里（按文件路径显式装载 `cruxline` 包 + 把各项目目录插到 `sys.path` 前面），
  配置在根 `pytest.ini`（`testpaths` / `pythonpath` / `--import-mode=importlib`）。

## 这轮改的东西

### 结构项（每个项目都补）

- 七份 README 全部有了 `## 已知边界`，写的是「什么情况下这份结论不可信」，每条指到 `文件:行号` 或实测读数。
- `console/` 补了 `pyproject.toml`（此前根本没有）与「快速开始」段（启动 + pytest + 六个 `/api/*` 的 curl 验活）。

### 顺带抓出的真缺陷（都先写失败测试再改）

| 项目 | 缺陷 | 修法 / 证据 |
| --- | --- | --- |
| geo-radar | 每个品牌只 `search` 首次出现，若首次出现被更长的品牌名包住，整条提及丢失 | 改为扫全部出现位置再按 span 去重取最早一条（`extract.py`）；复现 `"Bill.com is fine. Bill Gates also uses it."` |
| geo-radar | `mentions` 主键缺 `run_index`，同一 prompt 的多次采样被压成一条 | 主键加 `run_index`（`store.py`）；`run` 与 `report --run-id` 从 72→32 条不一致变为两侧都是 72 条、SoV 34.7%、位次 1.52 |
| geo-radar | 声量完全相等时印「落后 **X** 声量 **0.0%**」 | 加「持平」分支（`report.py`） |
| audit-loop | 现金科目匹配区分大小写，`Bank Account USD` 整批不匹配并全落到「银行已记企业未记」一侧 | 改 `casefold()` 子串匹配（`checks.py`）；正对照：中文科目仍匹配、非现金科目仍排除 |
| agent-store | CLI 完全没有参数解析，`main(argv)` 忽略 argv 直接跑 demo，`--help` 退出 0 却打印整段演示 | 改标准 argparse，裸调用行为不变（`agentstore/cli.py`） |
| filing-lens | `ingest.py` 裸 `except:` 吞掉事实抓取失败；`app/server.py` 4 处 `print` | 收窄异常类型 + `logger.warning`，降级行为不变；`print` 改 `logging` |
| filing-lens | README 写覆盖率阈值 `0.34`，代码是 `0.45` | 以代码为准改文档（`answer.py:18 MIN_COVERAGE`） |
| agent-inbox | README 的审批号还是 `AP-0001`，实现早已是 `AP-<实例令牌>-0001` | 按 `python3 -m agentinbox.cli demo` 的真实输出改文档 |
| 根 README | 测试数写 308 / filing 93 / cruxline「58/60、2 条失败」 | 现算改成 326 / 103 / 59/60（`1 条被否决`，磁盘满却宣称已推） |

## 三条共性教训

1. **文档漂移只在有第二份读数时暴露。** `0.34` 与 `0.45`、`AP-0001` 与 `AP-E284-0001`、`58/60` 与 `59/60`
   都是「修完代码没回头改文」。这类只有一条路能查出来：**跑一遍真命令，把输出和文档并排看**。
   读文档想不出来，读代码也想不出来。
2. **生成物会被当成项目判红。** 跑过测试后根目录长出 `.pytest_cache/`，验收脚本把它当成第八个项目，
   报「没有 README / 没有 pyproject / 没有边界段」——与「项目没打磨好」在输出上一模一样。
   所以 `GENERATED` 名单按名字排除，不靠「有没有 README」这种会被生成物满足的条件。
3. **「已修好的缺陷」写在边界段里比不写更糟。** geo-radar 与 audit-loop 的边界段初稿把我随后修掉的
   三条（多次出现丢失、落库压扁、大小写）当成「现存限制」写了进去——修完之后那些句子立刻变成假话。
   **改实现和改文档必须同一次提交**，否则下次读文档的人会按错误的边界做决策。

## 第二轮：把这份清单自己往后推

第一轮之后列了六条「还没打磨到的」。第二轮逐条处置，处置方式本身也是判据：
**能变成机器检查的就不留成待办，不能变的就写清为什么不变**。

| 待办 | 处置 | 落点 / 判据 |
|---|---|---|
| 跨项目 CLI 风格不统一 | 改成**契约测试**，不做公共包 | `tests/test_cli_contract.py`：六项 × 四条（`--help` 退出 0 且首行 `usage:`、`--version` 与 pyproject 版本一致、有 `demo`、未知子命令退出 2），24 例 |
| 错误类型无共享基类 | **决定不引入**，改由退出码契约对外 | 每个项目独立成仓库、彼此不 import；抽公共异常包会让「单独可用」变成「必须带另一个项目」。契约见上表第 4 条 |
| geo-radar `run`/`report` 两条路径 | 合并成一条 | 新建 `georadar/view.py`：`assemble()` 是内存侧入口、`load_view()` 是读库侧入口，`cmd_run` 也改成**落库后再读回来**打印，两条命令走同一个函数；`report.py` 加并列项兜底排序（只按 `-mentions` 排会让行序随输入顺序漂移）。`geo-radar/tests/test_single_path.py` 断言两条路径 markdown 逐字相同 |
| audit-loop 分析程序未进 CLI | 接进 `analytics` 子命令 | `auditloop/cli.py` 新增 `cmd_analytics`：`analytics --facts F [--json]`，退出码 0=跑完无异常 / 1=有异常 / 2=没跑成（文件缺失、JSON 坏、缺收入列）；文本行由 `--json` 字段逐字重建的断言在 `audit-loop/tests/test_cli_analytics.py` |
| `answer.py:_is_pure_cjk` 死代码 | **只报不删**（第 34 条） | 功能已被 `answer.py:322` 的 `if CJK_RE.search(question) and not groups:` 覆盖（那条注释写明「判据是中文没命中词表概念」）；删它属于「本次请求之外的重构」，等用户点头 |
| 没有端到端串联 | 新建 `scripts/e2e.py` + `tests/test_e2e.py` | 十个阶段跨六个项目真跑子进程；两处真交接（run_id 传给 report、run 报的品牌提及数必须等于 report 里的同一个数）+ 两处产物断言（底稿 ≥2000B、报告 ≥200B） |

**e2e 第一次跑就抓到真缺陷**：`cruxline judge --traces data/traces.jsonl` 抛
`json.decoder.JSONDecodeError: Extra data: line 2 column 1 (char 497557)` ——
`cmd_judge` 与 `cmd_calibrate` 都是 `load_traces(json.loads(open(...).read()))`，
把整份文件当一份 JSON 读，而仓库自带语料是 60 行 JSONL：**真实语料在命令行上根本判不了**。
单元测试全绿是因为它们喂 `fixtures.TRACES` 内存对象，从没走过文件。
修法：`cruxline/cruxline/cli.py` 新增 `_read_traces()`（`[` 开头按数组读，否则逐行读），
回归测试 `cruxline/tests/test_cli_traces.py` 三例（JSONL / JSON 数组正对照 / 仓库 60 条实录能判）。

第二条教训：**e2e 的第一个失败是我自己断言写错**（品牌行带「←」标记、那一列是每品牌提及数不是合计）。
串联脚本的断言错了会把「链好着」报成「链断了」，所以断言必须拿真输出对一遍再固化。

## 第三轮：结构化输出 + 全语料矩阵

| 事项 | 做法 | 判据 |
|---|---|---|
| `--json` 输出（原「风格不统一」的最后一条） | 四个**查询型**子命令加 `--json`：`filinglens ask`、`georadar run/report`、`cruxline judge`、`auditloop run`（`analytics --json` 早已有） | `tests/test_json_output.py` 六例：stdout **整体**是 JSON 对象；关键字段齐；能用 JSON 字段重建人读版本里的同一个数 |
| 全语料解析矩阵 | `scripts/corpus_matrix.py`（`--only` / `--json` / `--baseline`），基线存 `docs/corpus-matrix.json`；`make matrix` 逐份比对漂移 | `tests/test_corpus_matrix.py` 四例：22 份全解析、全带 XBRL、Apple 结构正常、退化形态**只有 Intel 一份** |
| `agent-inbox` / `agent-store` | 仍不加 `--json` | 它们只有 `demo`，没有可查询的命令；给演示稿套接口形状不算打磨，等有了 `route` / `statement` 再纳入 |

**第三轮抓到的真缺陷（比新增测试更值钱）**：`cruxline judge` 从来没用过产品自己的 rubric。
`cmd_judge` 写的是 `Judge(threshold=...)`，`Judge` 的默认 rubric 是 `judge.py` 里那套通用五条，
而产品与 `scripts/real_traces.py`、README 用的都是 `rubrics.agent_rubric()`（两个 fatal 项、权重合计 1.0）。
同一批 60 条真实轨迹：**命令行报 34/60 通过，文档写 59/60**，差 25 条且没有任何提示——
因为「判错了 rubric」在输出上只是数字偏小，不报错。
修法：`judge` 增加 `--rubric {agent,default}`，默认 `agent`；JSON 里带上 `"rubric"` 字段。
正对照测试显式要 `default` 时必须真的换过去（否则「默认对」可能只是写死）。

## 还没打磨到的（第三轮之后的诚实清单）

- ~~`agent-inbox` / `agent-store` 没有查询型子命令~~ 已处理一半：`agent-inbox` 补了
  `route` / `queue` 两条查询命令并纳入 `--json` 契约（审批落盘 `.agentinbox/approvals.jsonl`，
  `route` 写、`queue` 跨进程读）；`agent-store` 仍未纳入——它的 `statement` 会写账，
  是「变更」不是「查询」，要纳入得先决定幂等键怎么在命令行暴露。
- `filing-lens` 的中文提问靠 66 条词表桥接，词表外的问法直接拒答（既定边界，写进 README）。
- `_is_pure_cjk` 死代码仍在（等用户确认删除）。
- e2e 用固定 CIK（Apple）与固定夹具，不覆盖其余 21 份的解析差异——这条由 `make matrix`
  单独负责；但它在**每次提交**里不跑（两分钟），只在改解析器后手动跑。
  现在有棘轮兜住：基线记着产出它的解析器源码指纹（`parser_digest`），改了解析器而不重记基线，
  `tests/test_corpus_matrix.py::test_baseline_was_produced_by_the_current_parser` 直接红。
