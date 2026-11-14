# 第三轮审查：agent-inbox + agent-store + console

输入：三个项目的 README 与源码。下表与下文每一条结论都对应一次实际运行的输出，命令统一在 `/home/liuzewen/F:\deepseek` 下先 `cd` 到该根、再 `cd startup-clones/<proj>` 执行。

行号说明：引用的 README 行号对应当前工作树版本（`agent-store/README.md` 含 statement 段的未提交改动）。

范围说明：`agent-store` 的 `statement --json` 有同事在做（`git status` 里 `M agentstore/cli.py` / `M agentstore/meter.py` / `?? tests/test_statement_json.py`），那一部分**整体跳过**；`meter.statement()` 的分账数学只做独立复算，不评价其 JSON 契约。

---

## 断言清单（README 里可验证的 25 条）

| # | 断言原文 | 实测成立? | 证据命令 |
|---|---|---|---|
| A1 | `check_inbound`：非白名单 → 直接 blocked，**不进入模型**（agent-inbox/README.md:23） | 成立 | `Router(policy, memory, responder).handle("slack", {...mallory...})` → responder 调用 0 次 |
| A2 | 金额/破坏性/涉密/商务四类一律审批（README:24） | 部分成立（词表覆盖范围内成立，见 P2-5） | 逐条 `Policy.check_outbound` |
| A3 | 对外部发件人的回复默认入队，内部群聊才直发（README:25） | 成立 | `route --sender bob@acme.example …`（内部）delivered=True vs `--sender +8613800000001`（外部）delivered=False |
| A4 | `Memory.context(query, budget)` 加不下就停（README:26） | 成立 | `memory.context("余额 退款", 40)` → 3 行 / 34 字符 |
| A5 | 「演示输出（真实运行）」代码块（README:38-60） | **不成立**（P2-1） | `python3 -m agentinbox.cli demo` |
| A6 | `queue --json` 读 `route --store` 那份，跨进程可读（README:132-133） | 成立 | 两个独立进程：`route --store /tmp/r3store/ap.jsonl` 后 `queue --json --store …` |
| A7 | `route` 退出码 0=跑通（放行与拦截都算），2=用法错（README:136-137） | 成立 | 三次调用 exit 0 / 0 / 2 |
| A8 | 审批默认落 `.agentinbox/approvals.jsonl`（README:138） | 成立（但有仓库卫生副作用，P2-4） | `ls -la agent-inbox/.agentinbox` |
| A9 | `cli.py demo：5 条消息打穿全部路径（含一条恶意）`（README:111） | 成立 | demo 输出 5 条 + 3 条审批 |
| B1 | `publish` 拒绝同版本重发，`digest` 内容哈希入表（agent-store/README.md:11） | 成立 | `reg.publish(INVOICE_BOT, …)` 第二次 → `RegistryError: invoice-bot@1.2.0 已发布（digest=b47b8d3bd19a）` |
| B2 | 权限白名单 + 安装最小授权 + 执行前 `gate`（README:12） | 成立 | `install(granted=("secrets.read",))` → `RegistryError: 授权了清单里没有的权限` |
| B3 | `Runtime` **只在 handler 成功后写计量**（README:13） | 成立 | 被拦调用后 `select count(*) from usage` → 0 |
| B4 | `request_id` 是 usage 表主键，第二次直接返回原记录（README:14） | 成立（计费口径）；handler 跨进程会重跑（P1-3） | 同/新 Runtime 重投 `req-X` |
| B5 | 「演示输出（真实运行）」逐字（README:24-48） | 成立 | `python3 -m agentstore.cli demo` 与 README 逐行一致 |
| B6 | `per_token` 每 1k 向上取整（不足 1k 按 1k）（README:55） | 成立 | demo 2400 token → `$0.90`（3×1k） |
| B7 | `platform = round(gross × fee%)`，余数归开发者（README:58） | 成立 | 300 组随机账单逐行/合计复算，破例 0 组 |
| B8 | `demo` 默认 `:memory:`，`--db` 落盘（README:62） | 成立（本审查只用其落盘能力，statement 契约不评） | `python3 -m agentstore.cli demo --db /tmp/store-r3.db` |
| C1 | 「没有为演示另写逻辑：每个面板调的都是库里已经在跑的函数」（console/README.md:3） | **不成立**（P2-3） | 读 `console/app.py:159-265` |
| C2 | `pytest -q` → 11 passed（含跨线程竞态回归：filing 面板连打 5 次）（README:11） | 条数成立；**「跨线程竞态回归」不成立**（P1-1） | `python3 -m pytest -q` → 11 passed；`tests/test_console.py:44-53` 是串行 for |
| C3 | 七个 `/api/*` 验活全 200（README:17-19） | 成立 | `for p in …; curl -o /dev/null -w '%{http_code}'` |
| C4 | 依赖只有 `fastapi` 与 `uvicorn`（README:22） | 成立 | `console/pyproject.toml:5` |
| C5 | 「必须从 `console/` 目录启动」（README:23） | **不成立**（P2-2） | 从 `startup-clones/` 启动，七个接口全 200 |
| C6 | 份额表总和闭合到 100%（README:29） | 成立 | `sum(b["share"])` → 1.0（8 个品牌） |
| C7 | 拒答时出处为空（README:30） | 成立 | `pytest` 用例 `test_filing_refuses_without_citations` |
| C8 | 被拦调用写明 `permission_denied`，重投标「未重复计费」（README:39-40） | 成立 | `/api/store` JSON `reason`/`duplicate` 字段 |

未复核（诚实标注）：B 组「16 个 MCP server 审查」（README:151-191）依赖 `scripts/fetch_mcp_servers.py` 联网抓取 + 已 gitignore 的 `data/raw/`，本轮无网络素材，不评价其 0/16、13/16、9/16、high 5 / medium 11 的数字。

---

## 发现（按严重度）

### P0-1 并发下 filing 面板会返回**错误的财务数字**（HTTP 200，看起来完全正常）

- 位置：`console/app.py:93-104`（模块级 `_cache` 里存一个 `Answerer`，其 `conn` 被整个请求线程池共享）、`filing-lens/filinglens/facts.py:75-79`（`check_same_thread=False` + 注释「载入完成后本连接只做只读查询，因此允许跨线程使用是安全的」）、`facts.py:130-138`（`sorted(best.items())`）
- 复现（库层，确定性）：
  ```
  $ cd startup-clones && python3 -c "…8 线程 ×80 次 annual_series(共享 conn,'revenue')…"
  基线 revenue: [(2019, 64040000000.0), (2020, 64698000000.0), (2021, 365817000000.0), (2022, 394328000000.0), (2023, 383285000000.0), (2024, 391035000000.0), (2025, 416161000000.0), (2026, 478834000000.0)]
  8 线程×80 次: 异常 17, 结果错误 24
  错误样本0: [(0, None), (2019, 229234000000.0), (2020, 64698000000.0), …]
  错误样本1: [(2019, 88293000000.0), (2020, 64698000000.0), (2021, 365817000000.0), (2022, 365817000000.0), (2024, 391035000000.0), …]
  ```
  HTTP 层也撞到过一次 500（`/tmp/console8814.log`）：`console/app.py:104 filing → filinglens/answer.py:384 ask → answer.py:246 _metric_answer → facts.py:138 annual_series`，`TypeError: '<' not supported between instances of 'NoneType' and 'int'`。
- 为什么是缺陷：`check_same_thread=False` 只是关掉了 sqlite 的线程检查，并没有加锁；同一连接上并发 `execute().fetchall()` 会串游标——返回别的指标的行（2019 年营收变成 229.23B，真实 640.40B；2022 年混进 2021 的数）或 `fy=None`（`sorted` 直接 TypeError）。前者是 **200 + 错误结论**，比崩溃更危险：页面照常渲染一张错的营收表。
- 建议修法：`/api/filing` 的 `_cache` 加 `threading.Lock`（或改成每请求新建连接、`conn` 用 `check_same_thread=True` 且不复用），并把 `facts.py:75-78` 那句「只读所以安全」删掉——只读≠可并发。

### P1-1 README 声称的「跨线程竞态回归」测试是 5 次**串行**调用，测不到竞态

- 位置：`console/README.md:11`、`console/tests/test_console.py:44-53`
- 复现：
  ```
  $ grep -n "thread\|Thread\|range(5)" console/tests/test_console.py
  48:    for _ in range(5):
  $ python3 -m pytest -q
  11 passed in 2.53s
  ```
  用例 docstring 自称「SQLite 连接跨线程曾是间歇性 500（12 轮 pytest 炸 3 次）」，主体却是同一个 `TestClient` 上 `for _ in range(5)` 顺序请求。
- 为什么是缺陷：它把「同一进程内多打几次」当成跨线程验证，于是 P0-1 的竞态在 11 passed 的绿旗下继续存在（同一连接 8 线程实测 17 异常 / 24 错值）。这属于「测试自己变成 flaky 装饰」的反面：永不 flaky，因为永不并发。
- 建议修法：用 `concurrent.futures.ThreadPoolExecutor(8)` 对同一 client 并发打不同问法（不同问法才会 miss `Answerer` 的按问题缓存、真正复用连接），断言每次 `status=="ok"` 且数值等于单线程基线。

### P1-2 一个刷屏者 6 条消息就能锁死所有正常发件人（与 policy.py:66-68 注释相反）

- 位置：`agent-inbox/agentinbox/policy.py:92`（先扣全局桶）与 `:95`（后判单发件人桶）；注释在 `policy.py:65-68`「全局桶默认是单发件人桶的 2 倍：正常多客户并发不受影响」
- 复现：
  ```
  $ python3 -c "Policy(open_mode=True, rate_limit=3).check_inbound(spammer@evil.example) ×6 后 check_inbound(bob@acme.example)"
  spammer#1-3 allow=True | spammer#4-6 超出 3/60s 速率限制
  bob@acme.example → allow=False 超出全局 6/60s 速率限制
  ```
- 为什么是缺陷：被 per-sender 桶拒绝的重试已经在 `:92` 消耗了全局令牌，所以「自己刷被拒」等于替所有人花额度。README 承诺的「伪造 From 刷量拿到的额度有限且很小」只在攻击者用 100 个不同 From 时成立；**换成一个固定 From 连刷**，攻击者用 6 条即可让全局桶归零，与 `:65-68` 的注释直接矛盾。
- 建议修法：全局令牌只在 per-sender 桶放行之后扣（`_take_global_token` 移到 `:95` 之后），或对「被 per-sender 拒」的请求不计入全局桶。

### P1-3 agent-store 的幂等只在进程内：重启/多副本下同一 `request_id` 会重跑 handler，且回放标志为假

- 位置：`agent-store/agentstore/runtime.py:41-43`（`self._done` 进程内字典 + 注释「重投直接回放，不重跑 handler」）、`:55-61`（回放分支）
- 复现：
  ```
  $ python3 -c "…同 Runtime 重投 req-X；再新建 Runtime(同一 Ledger) 用同一 req-X…"
  同实例: charged=5 dup=True  handler 累计=1
  新实例: charged=5 dup=False handler 累计=2 | usage 表 (1, 5)
  ```
- 为什么是缺陷：README:14 的承诺是「客户端重投重复计费 → request_id 是 usage 表主键，第二次直接返回原记录」。计费确实没重复（usage 只有 1 行 `(1, 5)`），但**副作用被重复执行了两次**（handler 累计 2），且返回 `duplicate=False`、`charged_cents=5`——调用方据此无法区分「首次执行」和「重启后重放」，而 `runtime.py:41-43` 的注释是照着单进程写的。真实部署中重启、多副本、换 worker 都会踩到。
- 建议修法：把 `_done` 换成 Ledger 侧一张 `executions` 表（`PRIMARY KEY (buyer, request_id)`，存 output/error/charged/duplicate），或至少在跨进程里把 `charged_cents` 回放成 0 并置 `duplicate=True`。

### P2-1 agent-inbox README 的「真实运行」输出与真实运行不符（少 4 行审计、整段缺审批队列）

- 位置：`agent-inbox/README.md:38-60` vs `agent-inbox/agentinbox/cli.py:116-143`
- 复现：
  ```
  $ cd startup-clones/agent-inbox && python3 -m agentinbox.cli demo | grep -c "^  {"    # 审计行
  6
  $ python3 -m agentinbox.cli demo | grep -n "== 审批队列 =="
  13:== 审批队列 ==
  ```
- 为什么是缺陷：README 只贴了 2 行审计（`AP-E284-0003` 与 mallory 拦截），真实输出是 6 行 + 3 条审批队列 + 上下文样例；代码块里也没有「== 审批队列 ==」段。读者据此会以为 demo 不打印队列。「真实运行」这四个字把整段的证据价值抬高了，反而更该逐字对齐。
- 建议修法：把 `cli.py demo` 的输出整段复制进 README（含审批队列与 6 行审计），或反过来让 `cmd_demo` 只打印 README 里那几行。

### P2-2 console README「必须从 console/ 目录启动」不成立

- 位置：`console/README.md:23` vs `console/app.py:23-28`（`ROOT` 由 `__file__` 推导）
- 复现：
  ```
  $ cd startup-clones && python3 console/app.py --port 8819 &
  $ for p in projects geo filing audit crux inbox store; do curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8819/api/$p; done
  200 200 200 200 200 200 200
  ```
- 为什么是缺陷：文案比现实更严格，会让接手的人误以为有 cwd 依赖（`sys.path` 与 `data` 路径都是绝对化的）。
- 建议修法：改成「可以从任意目录启动；同级目录里要有那六个项目」。

### P2-3 console「没有为演示另写逻辑」与实际不符（两个面板手抄了 CLI 的演示场景）

- 位置：`console/README.md:3` vs `console/app.py:159-203`（`INBOX_PAYLOADS` + allowlist + 两条 memory 事实 + 摘要，与 `agentinbox/cli.py:116-143` 的 demo 场景重复）、`console/app.py:206-265`（`out` 字典、`calls` 六条调用序列、`granted` 授权，与 `agentstore/cli.py` 的 demo 重复）
- 复现：
  ```
  $ grep -n "INBOX_PAYLOADS\|req-1001\|账单\|out = {" console/app.py | head
  159:INBOX_PAYLOADS = [
  207:    out = {
  233:    calls = [("invoice-bot", ("fs.read",), "req-1001"),
  ```
- 为什么是缺陷：面板确实调的是库函数，但**场景数据是复制品**。CLI 的 demo 改一条消息、改一个价格，console 不会跟着变，页面上的「六个面板一致」也就不再证明任何跨项目一致性。
- 建议修法：把 demo 场景提取成 `agentinbox.cli.demo_scenario()` / `agentstore.cli.demo_scenario()` 供两边调用，或在 README 改口径为「面板复用库函数，场景数据为各面板内联的副本」。

### P2-4 按 README 默认路径跑 `route` 会往工作树里丢未跟踪目录

- 位置：`agent-inbox/agentinbox/queuefile.py:16`（`DEFAULT_PATH = Path(".agentinbox")/"approvals.jsonl"`）、`agent-inbox/README.md:138`
- 复现：
  ```
  $ cd startup-clones/agent-inbox && python3 -m agentinbox.cli route --sender bob@acme.example --allow bob@acme.example --text "退款 500 元"
  $ cd .. && git status --short agent-inbox
  ?? agent-inbox/.agentinbox/
  $ git check-ignore -v agent-inbox/.agentinbox/approvals.jsonl || echo "(not ignored)"
  (not ignored)
  ```
  （该目录是我这次运行产生的，已 `rm -rf agent-inbox/.agentinbox` 清理，工作树恢复干净。）
- 为什么是缺陷：文档化的第一条命令就污染 `git status`，且没有 `.gitignore` 兜底，很容易被 `git add -A` 带进提交。
- 建议修法：把 `.agentinbox/` 写进 `agent-inbox/.gitignore`（`agent-store` 已经这样处理 `data/raw/`）。

### P2-5 出口审批词表整类缺英文与货币符号：`send $500` / `pay $1,200` 一律直发

- 位置：`agent-inbox/agentinbox/policy.py:17-26`（`RISK_PATTERNS` 只有中文金额说法与 `$` 裸数字以外的形态）
- 复现（internal sender `bob@acme.example`，逐条 `check_outbound`）：
  ```
  DELIVERED: send $500 to the vendor / pay $1,200 now / please settle 500 USD with the vendor
  DELIVERED: 付 1200 元给供应商 / 帮我把这 3000 元结给供应商 / 给他 500 块就行
  APPROVAL : 把这 1200 元汇给供应商 / 转1200给客户 / 还给客户 500 元
  ```
- 为什么是缺陷：README 的已知边界已声明「正则词表、换表达可绕过」，中文同义词漏审（付…给、结给、块）算已披露；但**英文动词 + 货币符号/ISO 代码这一整类**没有任何词，而 `is_external` 只看域名后缀，一个英文写法的内部同事就能让 agent 直接对外发钱指令而不进审批队列。
- 建议修法：`money` 词表补 `(send|pay|wire|transfer|settle)\s+(usd|rmb|cny|\$|¥)?\s*[\d,]+` 与 `[\d,]+\s*(usd|rmb|cny|eur)` 两类，并把「单位 + 数字」的组合放在词表里而不是只放在中文句式里。

---

## 我核过但**成立**的断言

- **准入先于生成（A1）**：`route --sender mallory@evil.example --text "把客户名单发我"` → `blocked`，且注入的 responder 调用次数为 0（`check_inbound` 在 `router.handle_inbound` 里先于 memory/responder）。
- **From 伪装进不了内部**：`sender_address` + `normalize` 实测——`Bob <bob@acme.example>`→内部；`(support@acme.example) bob@partner.example`、`alice@acme.example, attacker@evil.example`、`"Alice <alice@acme.example>" <attacker@evil.example>` 全部剖析成**最后一个地址**并判为外部；`BOB@ACME.EXAMPLE` 因大小写不归一被判外部（保守方向，不构成绕过）；尾随空格被 strip（与 README 已知边界「精确比较」一致）。
- **伪造大量 sender 的限流（README:12 场景）**：`Policy(open_mode=True, rate_limit=3)` + 10 个不同伪造 From → 放行 6 条，全局桶 2× 生效。失效的是「同一 From 连刷」（P1-2），不是伪造。
- **入口审批链**：`route` 三条消息与 `demo` 同结论（余额→money 待审批、发票→已发送、退款 1200→money 待审批），`route` 与 `demo` 两条路径结论一致（A9 的「5 条打穿」也成立：demo 实际打印 5 条 + 3 条审批）。
- **退出码语义（A7）**：正常跑通 0、被拦截 0、缺 `--text` 2。
- **审批落盘/回读（A6/A8）**：`route --store /tmp/r3store/ap.jsonl` 写盘后，另一个进程 `queue --json --store …` 读到 `{"pending":[{"approval_id":"AP-0763-0001","risk":"money",…}]}`，exit 0。
- **上下文预算（A4）**：`Memory(budget_tokens=20)` + `context(..., 40)` → 3 行 / 34 字符，不超预算。
- **分成守恒（B7）**：300 组随机账单（1-40 个 agent、1-999 分、fee_pct ∈ {1,7,15,20,33,50,99,100}）→ `平台+开发者 != 总额` 的组数为 **0**；单行复算 `gross=1,1,2 @20%` 三行 platform 均为 0，与 `round()` 期望一致到分。
- **价格守卫**：`Pricing("per_call"/"subscription", cents_per_unit=-5/0)` 全部被 `拒绝 价格必须为正（美分）…` 拒掉，`cents=1` 通过（B1/B2 同批测）。
- **版本归属不可转移**：`northwind-labs` 发 `invoice-bot@1.2.0` 后，`attacker-labs` 发 `1.3.0` → `invoice-bot 属于 northwind-labs，attacker-labs 不能发布它的版本（首次发布即确立归属）`；`yank 1.2.0` 后 `latest` → `invoice-bot 的所有版本都已下架`。
- **权限闸不计费（B3）**：`needs=("secrets.read",)` 被拦（`permission_denied`），`charged_cents=0`，`select count(*) from usage` → 0。
- **`per_token` 向上取整（B6）**：demo 2400 token → `$0.90`（3 个 1k），与 README 一致；`demo` 输出与 README 逐字一致（B5，digest 三个前缀、$0.05/$0.90/$9.00、合计 $10.00、平台 $1.80/$0.18/$0.02）。
- **console 契约测试与降级**：`python3 -m pytest -q` → `11 passed`（条数与 README 一致，问题在用例语义，见 P1-1）；`/api/filing?cik=0000000001` → 200 `status="no_data"` + 可读提示（不缺数据时整页 500 不成立）；`/api/geo` 8 个品牌 `share` 合计 `1.0`；七个 `/api/*` 均 200（projects/geo/filing/audit/crux/inbox/store）。
- **冷启动并发不是崩溃而是慢**：20 并发冷启动 `/api/filing` → 全部 200，最大耗时 **63.0 s**（`console/app.py:93-101` 无 miss 合并，20 个线程各解析一遍 10-K）。README 未承诺延迟指标，故只记录不列为缺陷；但 30 s 默认超时的客户端会看到全量超时。
