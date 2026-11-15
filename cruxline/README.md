# cruxline

把「这算做好了」写成可执行 rubric，逐条判 agent 轨迹，并用人工一致性（Cohen's kappa）和版本回归证明**这把尺本身可信**。

一次 agent 运行 = 输入 + 工具调用序列 + 输出。评测对象是轨迹而不是最后那句话：工具调用里藏着大部分失败模式（没调工具就答、报错后继续编、死循环、改完不验证）。所以 `cruxline` 做的事有两层：

1. **判**：`rubrics.py` 里每条规则读轨迹的某一部分，算出 0–1 分；致命项一票否决。
2. **证明这把尺可信**：`calibrate` 拿人工标注算 kappa（不够就 BLOCK，不许上线当门禁），`diff` 比两版结果，`store` 把每次判定落库留痕。

## 安装

```bash
pip install -e .
# 开发（含 pytest）
pip install -e ".[dev]"
```

纯标准库实现，不需要任何运行时依赖。

## Quickstart：三条命令

```bash
# 1) 判一份轨迹（自带 OpenAI 风格示例，5 条：4 条过、1 条被硬否决）
python -m cruxline.cli judge --traces examples/traces-openai.jsonl

# 2) 想逐条看？加 --json，拿到 total / passed / pass_rate 与每条规则的分数与理由
python -m cruxline.cli judge --traces examples/traces-openai.jsonl --json

# 3) 和人工标注比一致性（示例标注：n=5 的演示，只用来演示口径）
python -m cruxline.cli calibrate --traces examples/traces-openai.jsonl \
    --labels examples/labels-expert.json --min-kappa 0.6
```

实测输出（本机真跑）：

```
通过率 80.0%（5 条 · rubric=agent）

样本 5 · 一致率 100.0% · kappa +1.000 · 门槛 0.6 · rubric=agent
人工通过率 80.0% / judge 通过率 80.0%
结论：PASS — judge 与人工标注一致性达标，可用于回归门禁
```

零配置看全部四个零件（轨迹 + 标注 + 校准 + 回归）：

```bash
python -m cruxline.cli demo
```

> `judge` 默认把每条判定写进 `cruxline.db`（机判/人判分表，历史不覆盖）。只想看分数不想留痕，就换一个库：`--db /tmp/scratch.db`。

## 换成你自己的轨迹

`cruxline/io.py` 的 `read_traces(path)` 负责把别人的轨迹读成 `Trace`：`.jsonl`（一行一条）与 `.json`（顶层数组）都吃，空文件返回 `[]`。字段别名：

| 位置 | 可用键名 |
| --- | --- |
| 轨迹 id | `case_id` / `id` / `caseId` / `trace_id` |
| 输入 | `input` / `question` / `prompt` / `user_input` |
| 输出 | `output` / `answer` / `response` / `final_output` |
| 工具调用列表 | `tool_calls` / `toolCalls` / `steps` / `actions` |
| 单次调用·工具名 | `name` / `tool` / `tool_name` |
| 单次调用·参数 | `args` / `arguments` / `input` |
| 单次调用·结果 | `result` / `output` / `observation` |
| 单次调用·错误 | `error` / `error_message` / `is_error`（布尔 `true` 且无文本时记成 `(unknown error)`） |

认不出来的记录直接抛 `ValueError`，消息里带**第几条**和**它有哪些键**：

```
ValueError: 第 2 条轨迹缺少 id（可用别名 case_id/id/caseId/trace_id），它有哪些键：['bar', 'foo']
```

`examples/` 里有 5 条 OpenAI 风格记录和逐条讲解（`examples/README.md`）。

## 改 rubric

一套 rubric 就是 `list[Criterion]`：

```python
# cruxline/rubrics.py
def agent_rubric() -> list[Criterion]:
    return [
        Criterion("turn_completed", 0.15, _turn_completed, fatal=True),
        ...
    ]
```

- `check` 是 `Trace -> (score, note)` 的纯函数，`note` 会原样打印进判定理由；
- `fatal=True` 的项得 0 分时整条 FAIL（加权平均会把致命问题平均掉）；
- 权重合计必须为 1.0，README 下面那张表由 `tests/test_review_r3.py::test_readme_rubric_table_matches_code` 逐行比对代码，手抄漂移会红；
- 改完先跑 `python -m pytest -q`，再用 `calibrate` 看新规则与人工标注还一不一致。

编码 agent rubric（`agent_rubric()`，权重合计 1.0，**两个**致命项）：

| 规则 | 权重 | 致命 | 抓什么 |
| --- | --- | --- | --- |
| `turn_completed` | 0.15 | ✅ | 回合异常结束（`reason=error` 或 `aborted`）；`interrupted` 不扣 |
| `error_recovered` | 0.25 | ✅ | 报错后既没补救也没说明失败，仍照常给出结论 |
| `no_loop` | 0.15 | | 同一 (工具, 参数) 连续重复 ≥3 次 |
| `retry_after_error_changed` | 0.15 | | 报错后原封不动重试 |
| `read_before_write` | 0.10 | | 没读过就 edit |
| `produced_answer` | 0.10 | | 没有结尾答复 |
| `verify_after_write` | 0.10 | | 末次写之后没有任何验证 |

为什么必须有硬否决：`examples/traces-openai.jsonl` 里的 `openai-5` 总分 0.750，**刚好达到**阈值 0.75，但它把 `rm -rf` 的 `Permission denied` 说成「已清理并推送成功」——`error_recovered` 一票否决，结论 FAIL。分数低不等于 FAIL，硬否决才是分水岭。

另一套 `support_rubric()`（= `judge.py` 的通用五条）给客服/工单类场景用：那里「工具报错」本身就是硬否决，不需要编码场景的「报错后补救」判定。CLI 默认 `--rubric agent`，换尺要显式写 `--rubric default`，两套 rubric 的通过率不可比。

## 命令

```
judge     --traces F [--rubric agent|default] [--threshold 0.75] [--json] [--db cruxline.db]
calibrate --traces F --labels L [--min-kappa 0.6] [--rubric ...] [--threshold 0.75]
diff      --before A.json --after B.json
demo
```

- `judge`：逐条 `Verdict`（分数、PASS/FAIL、命中的规则与理由、被哪条硬否决）；
- `calibrate`：与人工标注对照，给一致率 / kappa / 偏松偏严诊断，不达标返回码 2；
- `diff`：两版通过率、回归（原本过现在不过）、修复（原本不过现在过），结论 `ship|review|block|neutral`；
- 返回码：`0` 正常 / 结论不是 block，`2` 校准不达标或回归为 block。

## 真实语料上的实测

`data/sample-traces.jsonl`（5 条合成轨迹，覆盖 4 过 + 1 条「磁盘满却宣称已推」的否决样本）随包发布：

```bash
python -m cruxline.cli judge --traces data/sample-traces.jsonl    # 通过率 80%
```

作者本机另有 60 条真实 agent 会话轨迹（`scripts/export_dsh_traces.py` 导出，含生产内容，**不随仓库发布**）。用 `--rubric agent` 现算是：

```
60 条真实轨迹：PASS 59 / FAIL 1
步数中位数 8，最多 804；结束原因 {'completed': 57, 'interrupted': 2, 'error': 1}

各规则命中次数（0 分的规则才计入）：
  read_before_write            6 条    10%
  no_loop                      1 条     2%
  turn_completed               1 条     2%
  error_recovered              1 条     2%
  produced_answer              1 条     2%
  verify_after_write           1 条     2%
```

真实数据改掉了两条想当然的规则：

| 原本的规则 | 真实数据说什么 | 改成 |
| --- | --- | --- |
| `tool_diversity`：只用一种工具 = 没找对路 | 1829 次 bash vs 69 次 read —— 编码 agent 的工作**本来就**在 shell 里 | 换成 `verify_after_write`：改完文件之后有没有任何验证动作 |
| 回合没走到 `completed` 就算失败 | `interrupted` 是用户/压缩打断，不是 agent 的错 | 只有 `error` 才硬否决 |

两种真实样本（都是产物，不是噪声）：

```
session-f0014d4b-#t141  score=0.800 PASS
  - read_before_write:  未读取就编辑 .../PROVENANCE.md
  - verify_after_write: 2 次写，末次写之后没有任何验证动作
  ↑ 两条规则扣光，总分仍在阈值 0.75 之上

session-f0014d4b-#t2    score=0.600 FAIL  [硬否决: turn_completed,error_recovered]
  - turn_completed:  回合异常结束（error）
  - error_recovered: 工具报错后既未补救也未说明失败，仍照常给出结论
```

## 目录结构

```
cruxline/
├── cruxline/
│   ├── trace.py      Trace / ToolCall —— 评测对象
│   ├── io.py         read_traces：容器格式 + 字段别名 + 认不出来的记录报错
│   ├── judge.py      Criterion(weight, fatal) + Judge → 逐条 Verdict
│   ├── rubrics.py    agent_rubric() / support_rubric()，规则就读这一份
│   ├── calib.py      cohen_kappa / agreement / 偏松偏严诊断 / 门槛
│   ├── regress.py    diff → Regressions / Fixes / verdict
│   ├── store.py      SQLite：人判与机判分表，都带 labeler，历史不覆盖
│   ├── fixtures.py   8 条演示轨迹 + 专家标注 + 「新版」结果
│   └── cli.py        judge / calibrate / diff / demo
├── examples/
│   ├── traces-openai.jsonl   5 条 OpenAI 风格轨迹（4 过 1 否决）
│   ├── labels-expert.json    对应的人工标注
│   └── README.md             逐条为什么过/不过
├── data/             随包示例语料
├── tests/            89 条测试（含 CLI 真子进程）
├── scripts/          把本机会话日志导成轨迹的辅助脚本
├── pyproject.toml
└── LICENSE
```

## 路线图

- [x] 轨迹模型 / rubric / 硬否决 / kappa / 回归 / 落库 / 通用轨迹适配
- [ ] LLM judge 适配器（先过一致性门槛才允许参与打分）
- [ ] 多标注者一致性（Fleiss' kappa）+ 分歧样本回看队列
- [ ] 线上监控：滑窗通过率下降告警、按客户分群
- [ ] rubric 版本化（改了权重之后历史分数不可比，必须锁版本）

## 已知局限

- 规则 rubric 表达不了「语气是否得体」这类判断，需要 LLM judge 补位，而 LLM judge 本身也需要标注集校准。
- kappa 在样本 < 30 时极不稳定，当前的 8 条只是演示，不能当统计结论。
- 阈值 0.75 是约定不是定理；不同业务要各自标定。

## 许可证

MIT，见 `LICENSE`。
