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

## 现在的状态

- 七个项目 **硬项全过**（`7 个项目硬项全过。`）
- `python3 -m pytest` → **326 passed**（geo 31 / filing 103 / audit 40 / crux 52 / inbox 47 / store 42 / console 11）
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

## 还没打磨到的（诚实清单）

- 跨项目的 CLI 风格不统一：参数命名（`--brand/--cik/--run-id`）各写各的，没有统一的 `--json` 输出开关。
- 错误类型没有共享基类：六个包各自定义自己的异常，调用方无法用 `except AppError` 一次兜住。
- `geo-radar` 的 `run` 与 `report` 仍是两条代码路径（一份内存、一份落库），本次只保证两者一致，没有合并。
- `audit-loop` 的分析性程序仍未接进 CLI（`python -m auditloop.cli run` 只跑六项），README 的边界段已如实写明。
- `filing-lens` 的中文提问靠 66 条词表桥接，词表外的问法直接拒答；`answer.py` 里 `_is_pure_cjk` 是死代码。
- 七个项目的测试全部离线、无 mock 掉的断言，但**没有一次在同一份数据上做过端到端串联**
  （`console/` 是最接近的，它只验契约不验结论）。
