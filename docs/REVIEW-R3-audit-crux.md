# 第三轮审查：audit-loop + cruxline

审查员：第三方（无两个项目的开发历史，只信亲手跑出来的输出）
审查时间：2026-11-14
审查对象：`startup-clones/audit-loop`（README 117 行）、`startup-clones/cruxline`（README 130 行）

**取证前提（影响结论读法）**：`git rev-parse --show-toplevel` 在 `audit-loop/` 与 `cruxline/` 下都返回 `<仓库根>/startup-clones` —— 不是两个独立仓库，是同一仓库下的两个子目录（`startup-clones/.git`）。审查期间两个子目录本身没有任何未提交改动（`git status` 里的 9 项全是 `agent-store/`、`filing-lens/` 的他人改动）；我全程未做任何 git 写操作，自造的 `audit-loop/out/wp-review.xlsx`、`cruxline/cruxline.db` 已删除。两个项目的自带测试我都跑了，都是绿的（`audit-loop 50 passed`、`cruxline 61 passed`）—— 下面的 P0 全部发生在测试覆盖之外。

---

## 断言清单（README 里可验证的 30 条）

只录「可被一条命令或一次运行证伪」的断言。`## 已知边界` / `## 已知局限` 段里作者自认的边界不录（但它与实测冲突时仍记入发现，并标明出处是已知边界）。

| # | 断言原文 | 实测成立? | 证据命令 |
|---|---|---|---|
| A1 | `revenue_vs_receivables` 触发条件「应收增速 − 收入增速 > 20pt」，差 > 40pt 记 high | 成立 | `python3 -m auditloop.cli analytics --facts tests/fixtures/acme_annual.json` → `FY2026 ... 异常(high)`，文案 `差 +112.4pt` |
| A2 | `gross_margin_trend` 触发条件「毛利率同比变动 > 3pt」 | 成立 | 同上 → `FY2026 ... 异常(medium)`，`+3.9pt` |
| A3 | `cash_conversion` 触发「下滑 > 10pt 或相对下滑 > 25%」 | 成立 | 同上 → `FY2026 ... 异常(medium)`，`0.18 降至 0.13（28.6% 相对下滑）` |
| A4 | Apple 真实 XBRL：「收入年数=8 应收=18 毛利=18 经营现金流=15」+ 2 条例外（FY2021，+29.8pt / +3.5pt，均 medium） | 成立 | `cd audit-loop && python3 scripts/real_analytics.py ../filing-lens/data/0000320193_facts.json` |
| A5 | Microsoft 同口径 9 年数据无例外，阈值不是「总会报」 | 成立 | `python3 scripts/real_analytics.py ../filing-lens/data/0000789019_facts.json` → 输出 `没有分析性例外。` |
| A6 | 单步失败不终止整轮：`try/except → status=error` + `ref=ENGINE` 例外 | **部分成立**（AuditRun 层成立，`build_run` 真实接入路径不成立，见 P1-2） | 自建 `/tmp/r3probe/probe_engine.py`、`probe_buildrun.py` |
| A7 | 「只调节现金类科目」：`checks.reconcile_bank(accounts=...)` | 成立 | `grep -n "accounts_cf\|cash = " audit-loop/auditloop/checks.py`（:53-54） |
| A8 | 「调节差额必须能手工验算」→ `ReconResult.difference` | 成立 | `grep -n "difference" audit-loop/auditloop/checks.py` |
| A9 | 「底稿三页固定」摘要/例外/明细 | 成立 | `python3 -m auditloop.cli run --entity X --out out/a.xlsx && python3 -c "import openpyxl;print(openpyxl.load_workbook('out/a.xlsx').sheetnames)"` → `['摘要','例外','明细']` |
| A10 | 「每个程序必须挂一个审计认定」→ `models.py` 六个认定常量 | 成立 | `grep -n "^EXISTENCE\|^COMPLETENESS\|^CUTOFF" audit-loop/auditloop/models.py` |
| A11 | `python -m auditloop.cli demo` 可跑（内置 Acme 夹具，埋 6 类例外） | **不成立** | `python3 -m auditloop.cli demo` → `AttributeError`，EXIT=1（P1-1） |
| A12 | `python -m auditloop.cli run --entity ... --out out/workpaper.xlsx` 可跑 | 成立 | `python3 -m auditloop.cli run --entity '某制造有限公司' --out out/wp-review.xlsx`，EXIT=0 |
| A13 | 演示输出：`结论：attention_required（high 例外 3 条）`，六程序例外数 4/1/2/1/1/1 | 成立 | 同上，逐格比对 README:71-79 |
| A14 | 三条 high 例外 ref 为 `G3/G6`、`INV-1003`、`INV-1004` | 成立 | 同上（例外页三行） |
| A15 | 「只调节现金类科目」的补充：科目名大小写不敏感子串匹配 | 成立 | `grep -n "casefold" audit-loop/auditloop/checks.py`（:53） |
| A16 | `cli.py` 提供 run / analytics / demo 三个子命令 | 成立 | `python3 -m auditloop.cli --help` |
| A17 | 路线图 `[x]` 三个核心程序 + 重复付款 + 数据完整性 + 底稿导出 | 成立 | run 输出覆盖 6 个程序 |
| A18 | 结论「没有比较就报正常」应被排除：README 称「不再与『跑了且没问题』共用同一行输出」（已知边界段） | **不成立** | P0-1 |
| C1 | `python -m cruxline.cli demo` 全离线跑 8 条轨迹 + 标注 + 校准 + 回归 | 成立 | `python3 -m cruxline.cli demo`，EXIT=0 |
| C2 | demo 的 c3 `score=0.750 FAIL [硬否决: no_tool_error]`，明细 0.20/0.25/0.30 | 成立 | 同上，逐字一致 |
| C3 | demo 校准「样本 8 · 一致率 100.0% · kappa +1.000」→ PASS | 成立 | 同上 |
| C4 | demo 回归「25.0% → 37.5%（+12.5%）」「review · 回归 1 · 修复 2」「回归用例：c1」 | 成立 | 同上 |
| C5 | `judge --traces data/traces.jsonl --threshold 0.75 --json` 可跑 | 成立 | `python3 -m cruxline.cli judge --traces data/traces.jsonl --json` |
| C6 | 默认 `--rubric agent`；同一批 60 条 agent 59/60、default 34/60 | 成立 | `judge --traces data/traces.jsonl` vs `--rubric default` |
| C7 | 「60 条真实轨迹：PASS 58 / FAIL 2」 | **不成立** | P1-6 |
| C8 | 「步数中位数 8，最多 804；结束原因 {'completed': 57, 'interrupted': 2, 'error': 1}」 | 成立 | `python3 -c` 统计 `data/traces.jsonl` |
| C9 | 「1829 次 bash vs 69 次 read」 | 成立 | 同上统计 tool_calls |
| C10 | `turn_completed` 抓「回合异常结束（error）」；「只有 error 才硬否决」（interrupted 不算错） | **不成立** | P1-4 |
| C11 | 编码 agent rubric：「权重合计 1.0，只有一条致命项」，6 条，权重 0.15/0.20/0.20/0.15/0.15/0.15 | **不成立** | P1-5 |
| C12 | `read_before_write` 抓「没读过就 edit」 | 成立（行为对，代码有死条件，见 P2-4） | `grep -n "_read_before_write" -A8 cruxline/cruxline/rubrics.py` |
| C13 | `verify_after_write` 抓「末次写之后没有任何验证动作」 | 成立 | `grep -n "_verify_after_write" -A10 cruxline/cruxline/rubrics.py` |
| C14 | 真实命中的两条例外：`session-f0014d4b-#t141 score=0.700 FAIL`，两条扣分 | **不成立** | P0-3 |
| C15 | `calibrate --min-kappa 0.6`「先过一致性门槛（不达标不许上线当门禁）」 | **不成立**（门槛算的不是 judge 子命令用的那套 rubric） | P0-2 |
| C16 | `diff --before v1.json --after v2.json` 输出 `verdict(ship|review|block|neutral)`，删用例会 block | 成立 | `/tmp/r3probe/v1.json`、`v2.json`（删 c2/c3）→ `block`，EXIT=2 |
| C17 | `store.py`：人判与机判分表，都带 labeler，历史不覆盖 | 成立 | `grep -n "labeler\|INSERT" cruxline/cruxline/store.py` |
| C18 | 「阈值 0.75 是约定不是定理」（已知局限段）：改阈值结论随之改变 | 成立 | `--threshold 0.5/0.9/1.0` → 98.3% / 95.0% / 85.0% |
| C19 | 同一批轨迹跑两次给同一个数（`judge.py` 的可回归性） | 成立 | 两次 `--json` 完全相同（59/60、0.983333） |

---

## 发现（按严重度）

### P0-1 audit-loop：只有一个年度时，`gross_margin` / `cash_conversion` 判「正常」并 exit 0

- 位置：`audit-loop/auditloop/analytics.py:232-244`（`_items` 里 `status="flag" if f else "ok"`，对每个可用年份一律先给 `ok`）；配合 `audit-analytics` 只在相邻两年才可能产 finding（`analytics.py:85-93`）
- 复现：
  ```bash
  cd <仓库根>/startup-clones/audit-loop
  python3 -m auditloop.cli analytics --facts /tmp/r3probe/probe_single_year.json
  ```
  ```
  毛利率(%)  FY2026  本期 40.0  上期 —  变化 —  判定 正常
  现金含量(x) FY2026  本期 0.25  上期 —  变化 —  判定 正常
  EXIT=0
  ```
  `--json` 佐证：`[('revenue_vs_receivables','insufficient',None,None,''),('gross_margin','ok',40.0,None,'2026'),('cash_conversion','ok',0.25,None,'2026')]`，`summary {'total':3,'anomalies':0,'insufficient':1}`

  同一条缺陷在多年度夹具里也能看到（不是单年输入的怪癖）：
  ```bash
  python3 -m auditloop.cli analytics --facts tests/fixtures/acme_annual.json | grep FY2023
  ```
  ```
  毛利率(%) FY2023 本期 40.0 上期 — 变化 — 判定 正常
  现金含量(x) FY2023 本期 0.25 上期 — 变化 — 判定 正常
  ```
  首年没有可比上期，两项仍然被算进「共 11 项」的已经检过的名单里。
- 为什么是缺陷：这是「没查」被写成「查了没问题」——一个只有单年数据的账套，毛利率和现金含量两项根本没做比较，输出却盖「正常」并 exit 0，下游 `if rc==0` 的流水线会把它当干净数据归档。作者自己在 README 里把这件事列为最贵的失败（「不再与『跑了且没问题』共用同一行输出」），代码只在**缺列**时做到，**缺上期**时没做。
- 建议修法：在 `_items` 里，当 `prior is None`（该指标没有可比的前一年）时输出 `status="insufficient"` 且文案写「无可比上期」，同时让「全部指标 insufficient」走非 0 退出（与 P1-3 合并处理）。

### P0-2 cruxline：`calibrate` 校准的不是 `judge` 默认用的那套 rubric，把 rubric 差异误诊成「judge 偏严」

- 位置：`cruxline/cruxline/cli.py:93` `judge_map = _pass_map(Judge(threshold=args.threshold).score_all(traces))` —— `Judge()` 走 `DEFAULT_RUBRIC`；而 `judge` 子命令默认 `--rubric agent`（`cruxline/cruxline/cli.py:144`）。`calibrate` 子命令没有 `--rubric` 参数（`grep -n "\-\-rubric" cruxline/cruxline/cli.py` 只在 judge 里命中）。
- 复现（把 60 条人工标注设成「与 agent judge 完全一致」，这是校准门存在的唯一目的——检验判断一致，而不是检验 rubric 偏好）：
  ```bash
  cd <仓库根>/startup-clones/cruxline
  python3 -m cruxline.cli calibrate --traces data/traces.jsonl --labels /tmp/r3probe/expert_agree_with_agent.json --min-kappa 0.6
  ```
  ```
  样本 60 · 一致率 58.3% · kappa +0.043 · 门槛 0.6
  人工通过率 98.3% / judge 通过率 56.7%
  结论：BLOCK — judge 明显偏严，会制造假告警，先放宽阈值或补正例        EXIT=2
  ```
- 为什么是缺陷：人工标注与产品 judge 100% 一致，校准门仍然判 BLOCK，并把原因写成「judge 明显偏严」——它量的是没有人在用的 `DEFAULT_RUBRIC`（56.7% 通过率），于是把「两套 rubric 不同」这个事实报成「判断偏严」这种可行动假象。运维照着提示「放宽阈值」会真的把门放宽，而真实 judge 一条都没变。
- 建议修法：`cmd_calibrate` 增加 `--rubric {agent,default}`，默认 `agent`，与 `judge` 共用同一处 rubric 选择逻辑（把 `Judge` 的构造收成一个工厂函数，两处都调它）。

### P0-3 cruxline：README 用来证明「规则真能抓缺陷」的唯一样本号，现在判 PASS

- 位置：`cruxline/cruxline/rubrics.py:213,215`（`read_before_write 0.10`、`verify_after_write 0.10`，均非 fatal）vs `cruxline/README.md:97-103`
- 复现：
  ```bash
  cd <仓库根>/startup-clones/cruxline
  python3 scripts/real_traces.py | grep t141
  ```
  ```
  session-f0014d4b-#t141     score=0.800 PASS
  ```
  （README:100 写的是 `score=0.700 FAIL`，并列出两条 0 分扣分项）
- 为什么是缺陷：这条轨迹同时犯「没读过就 edit」和「改完文件不做任何验证」，两条规则各扣到 0 分，合计只掉 0.20 → 0.80 ≥ 0.75 判 PASS。规则表把这两条设成 0.10 的非致命项，等于承认「两条工作纪律全破仍然合格」；而 README 把它当**唯一**的「真实命中」实物证据，数字和判定都停在旧权重上。审查外部读者会照着 README 复现，得到相反结论。
- 建议修法：二选一并落测——① 把 `read_before_write` + `verify_after_write` 合并成一条 fatal 检查（「改文件必须先读、后验」）；② 保留权重，但把 README 的案例换成真实 FAIL 的 `#t2`（`error_recovered` 硬否决），并加一条断言「两条全 0 不得 PASS」的回归测试。

### P1-1 audit-loop：`demo` 子命令必崩（快速开始第一条命令）

- 位置：`audit-loop/auditloop/cli.py:125-127`（`ns = argparse.Namespace(entity="Acme Industrial", out="out/workpaper.xlsx")` 缺 `json`）→ `cli.py:101`（`if args.json:`）
- 复现：
  ```bash
  cd <仓库根>/startup-clones/audit-loop
  python3 -m auditloop.cli demo; echo "EXIT=$?"
  ```
  ```
  AttributeError: 'Namespace' object has no attribute 'json'      EXIT=1
  ```
  无任何业务输出、不写底稿（`out/` 下没有文件）。
- 为什么是缺陷：README:60 把 demo 列为拿到包之后的第一条命令；它先跑完了全部 6 个程序才崩在打印分支上，所以用户连「哪一步坏了」都看不到。`grep -rn "demo" audit-loop/tests` 零命中——50 个测试全绿也挡不住它。
- 建议修法：`Namespace(..., json=False)`；并加一条 subprocess 级测试断言 `demo` 的 EXIT=0 且 `out/workpaper.xlsx` 存在。

### P1-2 audit-loop：「单步失败不终止整轮」只对注册进 AuditRun 的闭包成立，`build_run` 的前置计算在保护圈外

- 位置：`audit-loop/auditloop/cli.py:30-31`（`rec = checks.reconcile_bank(ents, lines)`、`buckets = checks.ar_aging(invs, as_of)` 在 `run.register(...)` 之前求值）
- 复现（照 README:64「按 models.py 的三个 dataclass 逐行构造即可」的接入路径，只加一行为空科目名的脏行）：
  ```bash
  python3 /tmp/r3probe/probe_buildrun.py
  ```
  ```
  AttributeError: 'NoneType' object has no attribute 'casefold'   (checks.py:54)
  ```
  整轮带 traceback 终止，不产底稿，`status=degraded` 这条防线根本没被触达。
- 为什么是缺陷：README 把「现场数据永远有脏行」当作设计前提，engine 也真的实现了捕获（我验证过：注册进 `register()` 的闭包抛异常 → `status=degraded` + `ref=ENGINE` 的 high 例外 + 「失败程序追踪」进 markdown）。但真实用户走的是 `build_run`，那里两行语句就跑在保护圈外——最需要容错的地方恰好没有容错，且失败形态是「什么底稿都没生成」，不是「降级底稿」。
- 建议修法：把 `rec`/`buckets` 的计算移进对应 step 闭包内部（或包一层 `try/except` 转成 `status=error` 的 StepResult），使 `register` 成为唯一的执行入口。

### P1-3 audit-loop：三项指标全部「数据不足」时仍 exit 0

- 位置：`audit-loop/auditloop/cli.py:158-166`（docstring 自述「0=跑完无异常、1=跑完有异常、2=根本没跑成」）+ `cmd_analytics` 末尾 `return 0` 的路径
- 复现：
  ```bash
  cd <仓库根>/startup-clones/audit-loop
  python3 -m auditloop.cli analytics --facts tests/fixtures/revenue_only.json; echo "EXIT=$?"
  ```
  ```
  Sparse Co · 分析性程序
  应收增速差(pp) 本期 — 上期 — 变化 — 判定 数据不足
  毛利率(%) 本期 — 上期 — 变化 — 判定 数据不足        EXIT=0
  ```
  （完整输出三行均为 `判定 数据不足`，`现金含量(x)` 同上）
- 为什么是缺陷：作者把退出码分三档的**唯一理由**写在 docstring 里（「把 1 压成 0 会让背离在流水线上与干净数据无法区分」），但「一条指标都没算成」被归进了 0。CI 无法区分「查了没异常」和「什么都没查出来」——正是 P0-1 的同源问题在退出码层面的表现。
- 建议修法：统计 `insufficient == total` 时 `return 2`（或新增 3=无法判定），stderr 说明缺哪几列/哪几年的数。

### P1-4 cruxline：`turn_completed` 按 `meta.aborted` 判定，README 说按「结束原因 error」

- 位置：`cruxline/cruxline/rubrics.py:148-150`
  ```python
  reason = t.meta.get("reason") or ("aborted" if t.meta.get("aborted") else "completed")
  return (0.0, f"回合异常结束（{reason}）") if t.meta.get("aborted") else (1.0, f"结束原因 {reason}")
  ```
- 复现：
  ```bash
  python3 -c "import sys;sys.path.insert(0,'.');from cruxline.rubrics import _turn_completed;from cruxline.trace import Trace
  [print(m,'->',_turn_completed(Trace('x','i','o',[],m))) for m in ({'reason':'error'},{'reason':'error','aborted':True},{'reason':'interrupted'})]"
  ```
  ```
  {'reason': 'error'} -> (1.0, '结束原因 error')
  {'reason': 'error', 'aborted': True} -> (0.0, '回合异常结束（error）')
  ```
- 为什么是缺陷：同一字段被两种读法对待——note 里把 `reason` 当证据写「结束原因 error」，打分却只看 `aborted` 布尔。一条标了 `reason=error` 却没有 `aborted` 的轨迹（不同导出器很容易漏这个字段）会拿满 0.15 分并打印「结束原因 error」，读日志的人以为它被抓了，实际上一分没扣。README:84/90 明确写的是「只有 error 才硬否决」。
- 建议修法：判定改成 `if t.meta.get("aborted") or (t.meta.get("reason") == "error")`，并在 `trace.py` 的规范化里让两个字段互推，避免同一事实有两个真相。

### P1-5 cruxline：README 的 rubric 表只有 6 条、声称「只有一条致命项」，代码是 7 条、两个 fatal

- 位置：`cruxline/README.md:86-95` vs `cruxline/cruxline/rubrics.py:209-215`
  ```
  209: Criterion("turn_completed", 0.15, _turn_completed, fatal=True)
  210: Criterion("error_recovered", 0.25, _error_recovered, fatal=True)
  213: Criterion("read_before_write", 0.10, _read_before_write)
  215: Criterion("verify_after_write", 0.10, _verify_after_write)
  ```
- 复现：
  ```bash
  python3 -c "from cruxline.rubrics import agent_rubric; cs=agent_rubric(); print(len(cs), sum(c.weight for c in cs)); print([(c.name,c.weight,c.fatal) for c in cs])"
  ```
  ```
  7 1.0
  [('turn_completed', 0.15, True), ('error_recovered', 0.25, True), ('no_loop', 0.15, False),
   ('retry_after_error_changed', 0.15, False), ('read_before_write', 0.1, False),
   ('produced_answer', 0.1, False), ('verify_after_write', 0.1, False)]
  ```
- 为什么是缺陷：表里完全没有 `error_recovered` —— 而它正是把 `#t2` 判 FAIL 的那一条（`scripts/real_traces.py` 输出 `error_recovered 1 条 2%`）。同一份 README 第 20、36、38 行都写「两个 fatal 项」，与第 86 行的「只有一条致命项」自相矛盾；`no_loop` 0.20→0.15、`read_before_write` 0.15→0.10、`produced_answer` 0.15→0.10、`verify_after_write` 0.15→0.10 四处权重也不对（合计 1.0 这一点倒是对的）。读者照这张表重实现，会得到一个只有一条硬否决、权重分配全错的 judge。
- 建议修法：表重写成 7 行、按代码顺序、标出两个 fatal；更好的做法是从 `AGENT_RUBRIC` 生成这张表（`python -c` 打印 markdown），彻底消除手抄漂移。

### P1-6 cruxline：README 的真实轨迹结论是旧数字（PASS 58/FAIL 2，实测 59/1）

- 位置：`cruxline/README.md:75`（与同文件 37-39 行的 `agent 59/60` 自相矛盾）
- 复现：
  ```bash
  cd <仓库根>/startup-clones/cruxline
  python3 scripts/real_traces.py | head -2
  ```
  ```
  60 条真实轨迹：PASS 59 / FAIL 1
  步数中位数 8，最多 804；结束原因 {'completed': 57, 'interrupted': 2, 'error': 1}
  ```
- 为什么是缺陷：这是项目对外的头条结果，且和第 37 行的 59/60 互相打脸——读者无法判断哪个是当前真相。数字口径错本身就会让整段「真实数据改掉了我两条想当然的规则」的可信度打折（相邻的中位数/最大值/结束原因分布我全核对过，都对，说明只是这一处没跟着权重改动更新）。
- 建议修法：把 `README:74-77` 的代码块改成 `scripts/real_traces.py` 生成，或删掉手抄数字只留命令。

### P1-7 audit-loop：severity 是自由字符串，拼写变体让「有 high 例外」和 `status=clean` 同时成立

- 位置：`audit-loop/auditloop/engine.py:62-63`（`return [f for f in self.findings if f.severity == "high"]`，精确匹配）vs `models.py:56-63`（注释承诺「未知严重度按 medium 排序，不许让一个拼错的字符串崩掉整张底稿」）
- 复现：
  ```bash
  python3 /tmp/r3probe/probe_sev2.py
  ```
  ```
  severity='high'   status=attention_required   high=1
  severity='HIGH'   status=clean                high=0
  高                status=clean                high=0
  ```
- 为什么是缺陷：`models.py` 只给「排序」做了未知值兜底（`severity_rank` → 2），没给「结论」做——例外行照样进底稿清单，摘要结论却是 `clean`。README 把 `status=clean` 定义为「无程序报错且无 high 例外」，一个 `"HIGH"` 就让这句话在字面上成立、在实践中骗人。触发条件是调用方用 ERP 导出的大小写原值填 `severity`（字段是裸 `str`，没有任何校验）。
- 建议修法：`Finding.__post_init__` 里 `self.severity = self.severity.strip().lower()`，非 `{high,medium,low}` 直接抛 `ValueError`（或按 medium 归一并记一条明显警号）。

### P2-1 audit-loop：README 已知边界段的代码行号已漂移

- 位置：`audit-loop/README.md:111`（引 `checks.py:39,50`）、`:113`（引 `checks.py:115`）、`:111`（引 `checks.py:122`）
- 复现：`grep -n "if not inv.recognized\|tolerance_days\|accounts_cf = " audit-loop/auditloop/checks.py`
  ```
  53:    accounts_cf = tuple(a.casefold() for a in accounts)
  119:    tolerance_days: int = 0
  126:        if not inv.recognized:
  ```
- 为什么是缺陷：这一段的用途就是「指到实现位置」，读者点进去看到的是别的代码，边界说明的可核查性归零（`checks.py:50` 处现在是注释，`122` 处是别的分支）。
- 建议修法：改用函数名 + 代码片段而不是行号（`checks.reconcile_bank` 里的 `accounts_cf`），或加一个脚本在 CI 里校验行号引用。

### P2-2 audit-loop：README 演示输出里的日期格式与实际不一致

- 位置：`audit-loop/README.md:81`
- 复现：`python3 -m auditloop.cli run --entity '某制造有限公司' --out out/wp-review.xlsx | grep Northwind`
  ```
  Northwind 在 2026-09-20 与 2026-09-21 各付 800.00，疑似重复付款
  ```
  （README 写的是 `09-20 与 09-21`）
- 为什么是缺陷：只影响「演示输出（真实运行）」这段标题下的可信度——一个号称贴真实输出的块，格式对不上说明它是手改过的。
- 建议修法：按实际输出重贴，或把这段也改成跑出来的。

### P2-3 cruxline：空轨迹文件给裸 `ZeroDivisionError`，缺文件给裸 `FileNotFoundError`

- 位置：`cruxline/cruxline/cli.py:74`（`rate = passed / len(verdicts)`）
- 复现：
  ```bash
  python3 -m cruxline.cli judge --traces /tmp/r3probe/empty.jsonl; echo "EXIT=$?"
  ```
  ```
  ZeroDivisionError: division by zero      EXIT=1
  ```
- 为什么是缺陷：退出码非 0 是对的，但对 CI 只留下 traceback、没有「输入为空」这种可行动信息；与 audit-loop 的 2=没跑成 相比，这里的错误分类缺失。
- 建议修法：`if not traces: print("轨迹文件为空", file=sys.stderr); return 2`，并把 json 解析失败统一成同样的诊断行。

### P2-4 cruxline：`_read_before_write` 里的死条件（`and call.name == "edit"` 抹掉了 `write`）

- 位置：`cruxline/cruxline/rubrics.py:135`
  ```python
  if call.name in ("edit", "write") and path not in read and call.name == "edit":
  ```
- 复现：`grep -n "call.name in" cruxline/cruxline/rubrics.py` → 上一行即命中
- 为什么是缺陷：前半个成员测试永远不起作用，`write` 从不触发「没读过就写」；行为上与 README 描述的「没读过就 edit」一致（所以不是结论错），但代码表达的是另一回事——下一个人要么误以为 write 已被覆盖，要么在这个条件上继续叠加逻辑。
- 建议修法：若只查 edit，就写成 `if call.name == "edit" and path not in read:`；若要覆盖 write，删掉尾巴那个条件并补测试。

### P2-5 cruxline：`judge` 有未文档化的落库副作用

- 位置：`cruxline/cruxline/cli.py` 的 `--db`（默认 `cruxline.db`）+ `store.py`
- 复现：`cd cruxline && python3 -m cruxline.cli judge --traces data/traces.jsonl >/dev/null && ls -l cruxline.db`
  ```
  -rw-r--r-- 1 liuzewen liuzewen 32768 Nov 14 06:01 cruxline.db
  ```
  `grep -n '"--db"' -A1 cruxline/cli.py` → `j.add_argument("--db", default="cruxline.db")`（:142）
- 为什么是缺陷：README 把 judge 描述成「只判分、可回归」的纯命令，实际在 CWD 落了 sqlite（命中 `.gitignore:6 *.db`，不会污染仓库，但会污染 CI 的产物目录和只读挂载）。文档里的架构段提到了 `store.py`，但没写「judge 默认会写库」。
- 建议修法：README 补一句，或让 `--db` 默认 None（只有显式给了才落库）。

---

## 我核过但**成立**的断言

下面每一条都是我自己跑了才敢写下来的（命令见断言清单的「证据命令」列），没有一条是照抄 README：

- **audit-loop 的 6 程序演示输出逐格对得上**：`结论：attention_required（high 例外 3 条）`，bank_recon 4 / ar_aging 1 / revenue_cutoff 2 / duplicate_payment 1 / ar_sanity 1 / ar_completeness 1，ref 是 `G3/G6`、`INV-1003`、`INV-1004`。README:69-84 这一块是可信的（唯一偏差是 P2-2 的日期格式）。
- **Apple / Microsoft 两个真实 XBRL 结果与 README 完全一致**：Apple 8 年收入序列、FY2021 两条 medium（+29.8pt、+3.5pt）；Microsoft 9 年「没有分析性例外。」EXIT=0。README 拿它当「阈值不是装饰」的证据，这个论证站得住。
- **engine 层的异常隔离真的有效**（我自造了抛异常、返回空 dict、返回非 list 三种坏程序）：异常 → `status=error` + `ref=ENGINE` 的 high 例外 + 整体 `degraded`，且 `to_markdown()` 里确实出现「失败程序追踪」。README:49/115 的纪律在 `AuditRun` 这一层成立（失效的是 `build_run` 的外围，见 P1-2）。
- **底稿确实是固定三页** `['摘要','例外','明细']`，`ReconResult.difference` 存在且是纯算术，可手工验算。
- **`analytics` 的缺列/坏 JSON 退出码是对的**：`{'years':{}}` 与 `{'years':{'2026':{}}}` 均 exit 2 并在 stderr 说清缺什么；`acme_annual.json` exit 1、`clean_annual.json` exit 0。
- **cruxline 两套 rubric 的差异是真的、方向也对**：`agent 59/60（98.3%）` vs `default 34/60（56.7%）`，与 README:37-39 完全一致。
- **judge 是确定性的**：同一批轨迹两次 `--json` 输出完全相同（59/60、0.983333、`a == b` 为 True）。没有隐藏随机源。
- **`--threshold` 单调且真的改变结论**：0.5 → 98.3%、0.9 → 95.0%、1.0 → 85.0%。
- **硬否决在阈值边界生效**：我自造一条 `score=0.75` 的轨迹（0.75 ≥ 0.75 本该 PASS），带 `error_recovered` 失败时 `passed=False`、`vetoed=['error_recovered']`。README:12 的「致命项一票否决」成立。
- **回归比对在「基线有用例、现在没有」时确实 block**：v1=`{c1:T,c2:T,c3:F}`、v2=`{c1:T}` → `结论：**block** · 回归 0 · 修复 0`，并明确列出 `未执行用例（2）：c2, c3 —— 用例集不一致，通过率不可比`，EXIT=2。这是 README 里唯一有 fail-closed 语义的门，做得对。
- **忽略未执行用例、不拿缺测当修复**这点也没做错——它只是不参与通过率，但结论被降级为 block，符合「删除用例不算修好」的直觉。
- **demo 的三段输出与 README:49-61 逐字一致**（c3 明细 0.20/0.25/0.30、校准样本 8 kappa +1.000、回归 25.0%→37.5% 且回归用例 c1、修复 c2/c6），EXIT=0。
- **轨迹统计全对**：n=60、步数中位数 8.0、最大 804、`{'completed': 57, 'interrupted': 2, 'error': 1}`、`bash 1829 / read 69`。README:76、83 这组数字是用真实数据算过的，不是编的。
- **两个测试套件都绿**：`audit-loop 50 passed`、`cruxline 61 passed`。这条既是我核过的「成立」项，也是上面多个 P0/P1 的成因——`grep -rn "demo\|t141" audit-loop/tests cruxline/tests` 零命中，README 里最显眼的两个实例断言没有任何测试盯着。
