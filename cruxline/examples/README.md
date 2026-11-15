# cruxline

示例语料：5 条 OpenAI 风格轨迹（`id` / `question` / `answer` / `steps`），
用来验证 `cruxline.io.read_traces` 的字段别名映射，并给出一份能直接对比的基线。

## 实测结果

```bash
python -m cruxline.cli judge --traces examples/traces-openai.jsonl
```

```
通过率 80.0%（5 条 · rubric=agent）
```

即 4 条通过、1 条被 `error_recovered` 一票否决。逐条原因：

| id | 结论 | 为什么 |
| --- | --- | --- |
| `openai-1` | PASS | 只跑了一次测试且成功，有结尾答复，无报错、无循环 |
| `openai-2` | PASS | 先读 README 再 grep，两次调用都成功，答复覆盖了快速开始的三步 |
| `openai-3` | PASS | 先 `read utils.py` 再 `edit` 同一路径（过 `read_before_write`），末次写之后跑了测试（过 `verify_after_write`） |
| `openai-4` | PASS | 读 → 改 → 再读回确认，写后有成功验证 |
| `openai-5` | **FAIL** | 第二步 `rm -rf` 报 `Permission denied`（`is_error: true`），之后没有任何成功动作补救，结尾仍写「已清理并推送成功」→ `error_recovered` 得 0 分并触发硬否决；总分 0.750 已过阈值 0.75，**分数够但被否决**，这正是硬否决存在的理由 |

## 换成你自己的轨迹

`read_traces` 认这些别名（任选一种，混用也行）：

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

`.jsonl`（一行一条）与 `.json`（顶层数组）都接受；空文件返回空列表。
认不出来的记录直接报错，消息带**第几条**和**它有哪些键**，例如：

```
ValueError: 第 2 条轨迹缺少 id（可用别名 case_id/id/caseId/trace_id），它有哪些键：['bar', 'foo']
```

## 人工标注示例

`labels-expert.json` 是对这 5 条的人工判定（前 4 条过、第 5 条不过），
用来演示 `calibrate` 的口径，不代表统计结论（n=5，kappa 不稳定）：

```bash
python -m cruxline.cli calibrate --traces examples/traces-openai.jsonl \
    --labels examples/labels-expert.json --min-kappa 0.6
```
