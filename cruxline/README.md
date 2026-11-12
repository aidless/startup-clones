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
python -m cruxline.cli judge --traces traces.json --threshold 0.75
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
