# cruxline

把企业专家脑子里的「这算做好了」变成 **可执行 rubric + 人工一致性校准 + 版本回归门禁**。

> 对标：Crux Labs（纽约，2026-10-30 $6M+ 种子）。它卖的核心不是模型，是「用你自己的专家判断来评测和监控 agent」。这里把它拆成四个可验证零件：轨迹模型、rubric 打分、kappa 校准、回归比对。

## 三个现实问题，对应三行代码

| 现实问题 | 后果 | 本项目的处理 |
| --- | --- | --- |
| 一堆人肉看对话记录 | 无法规模化，也无法证明「新版更好」 | `trace.py` 固定轨迹结构（输入/工具链/输出/期望要点） |
| 规则平均分把致命问题平均掉 | 「工具报错后编造单号」得分 0.75 竟然过了 | `judge.py` **硬否决**：致命项一票否决 |
| judge 自说自话 | 上线后疯狂假告警或放过真问题 | `calib.py` Cohen's kappa + 偏松/偏严诊断 |

## 为什么 90% 的 agent 评测项目会失败

1. **只测最终答案**。agent 的失败多在过程里：没调工具就答（c2）、报错后继续编（c3）、死循环（c5）。所以评测对象必须是轨迹。
2. **用平均分**。「有 5 条致命问题」不会让平均分掉到阈值以下。所以必须有硬否决。
3. **没有校准**。一个「全判 PASS」的裁判在 90% 正例的数据上一致率也是 90%，但它什么都没测出来 —— 这就是必须用 kappa 而不是一致率的原因。
4. **只看总通过率**。25% → 37.5% 可能是修好 2 个、弄坏 1 个，被弄坏的往往是大客户在用的那条（本项目 demo 就是这个剧本：修好 c2/c6，弄坏 c1，结论 `review` 而不是 `ship`）。

## 快速开始

```bash
cd cruxline
pip install -e .

python -m cruxline.cli demo        # 8 条轨迹 + 专家标注 + 校准 + 回归，全离线
```

真实使用：

```bash
# 1) 从生产打点导出轨迹
python -m cruxline.cli judge --traces data/traces.jsonl --threshold 0.75 --json
# 默认 --rubric agent（回合没走完、报错后编造结论这两项一票否决）；
# 换 --rubric default 是 judge.py 里的通用五条——同一批 60 条：agent 59/60、default 34/60。
# --rubric 默认 agent（产品自身那套，两个 fatal 项）；--rubric default 是 judge.py 的通用五条
# 实测仓库 60 条真实轨迹：agent 59/60 通过，default 34/60 —— 两套 rubric 不能混用
# 2) 专家标注 30 条，先过一致性门槛（不达标不许上线当门禁）
python -m cruxline.cli calibrate --traces traces.json --labels expert.json --min-kappa 0.6
# 3) 每次发版比一次
python -m cruxline.cli diff --before v1.json --after v2.json
```

## 演示输出（真实运行）

```
c3 score=0.750 FAIL  [硬否决: no_tool_error]
    uses_tool              1.00 × 0.20  1 次工具调用
    no_tool_error          0.00 × 0.25  工具报错：create_refund
    answers_expected_terms 1.00 × 0.30  命中 2/2 个期望要点      ← 分够高，但编造了单号

== 一致性校准 ==
样本 8 · 一致率 100.0% · kappa +1.000
结论：PASS — judge 与人工标注一致性达标，可用于回归门禁

== 版本回归（新版修好 c2/c6，弄坏 c1）==
通过率 25.0% → 37.5%（+12.5%）
结论：**review** · 回归 1 · 修复 2
回归用例：c1
```

## 真实轨迹：60 条 dsh 会话（我自己跑出来的）

夹具是我编的 8 条轨迹，只能证明规则会算数。真实轨迹是 `~/.dsh/sessions` 里的会话日志，
一键导出（`scripts/export_dsh_traces.py`），不带任何标准答案——评分器只看**过程**。

```bash
python scripts/export_dsh_traces.py --limit 60 --min-steps 4
python scripts/real_traces.py
```

```
60 条真实轨迹：PASS 58 / FAIL 2
步数中位数 8，最多 804；结束原因 {'completed': 57, 'interrupted': 2, 'error': 1}
```

真实数据改掉了我两条想当然的规则：

| 原本的规则 | 真实数据说什么 | 改成 |
| --- | --- | --- |
| `tool_diversity`：只用一种工具 = 没找对路 | 1829 次 bash vs 69 次 read —— 编码 agent 的工作**本来就**在 shell 里 | 换成 `verify_after_write`：改完文件之后有没有任何验证动作 |
| 回合没走到 `completed` 就算失败 | `interrupted` 是用户/压缩打断，不是 agent 的错 | 只有 `error` 才硬否决 |

编码 agent rubric（权重合计 1.0，只有一条致命项）：

| 规则 | 权重 | 致命 | 抓什么 |
| --- | --- | --- | --- |
| `turn_completed` | 0.15 | ✅ | 回合异常结束（`error`） |
| `no_loop` | 0.20 | | 同一 (工具, 参数) 连续重复 ≥3 次 |
| `retry_after_error_changed` | 0.20 | | 报错后原封不动重试 |
| `read_before_write` | 0.15 | | 没读过就 edit |
| `produced_answer` | 0.15 | | 没有结尾答复 |
| `verify_after_write` | 0.15 | | 末次写之后没有任何验证 |

真实命中的两条例外（是产物，不是噪声）：

```
session-f0014d4b-#t141  score=0.700 FAIL
  - read_before_write:  未读取就编辑 .../g24_davis19_tail/PROVENANCE.md
  - verify_after_write: 2 次写，末次写之后没有任何验证动作
```

## 架构

```
trace.py     Trace / ToolCall —— 评测对象
judge.py     Criterion(weight, fatal) + Judge → 逐条 Verdict（含 vetoed 原因）
calib.py     cohen_kappa / agreement / 偏松偏严诊断 / 门槛
regress.py   diff → Regressions / Fixes / verdict(ship|review|block|neutral)
store.py     SQLite：人判与机判分表，都带 labeler，历史不覆盖
fixtures.py  8 条轨迹 + 专家标注 + 「新版」结果
```

## 路线图

- [x] 轨迹模型 / rubric / 硬否决 / kappa / 回归 / 落库
- [ ] LLM judge 适配器（先过一致性门槛才允许参与打分）
- [ ] 多标注者一致性（Fleiss' kappa）+ 分歧样本回看队列
- [ ] 线上监控：滑窗通过率下降告警、按客户分群
- [ ] rubric 版本化（改了权重之后历史分数不可比，必须锁版本）

## 已知局限

- 规则 rubric 表达不了「语气是否得体」这类判断，需要 LLM judge 补位，而 LLM judge 本身也需要标注集校准。
- kappa 在样本 < 30 时极不稳定，当前的 8 条只是演示，不能当统计结论。
- 阈值 0.75 是约定不是定理；不同业务要各自标定。

MIT License.
