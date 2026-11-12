# agent-inbox

把 email / iMessage / WhatsApp / Slack 收进**一个常驻 agent**，并且让它**有边界**：准入白名单、令牌桶限流、金额与破坏性动作一律走审批、上下文按预算拼装、每一步留审计。

> 对标：Inkbox（2026-11-09 $5.3M 种子，Peak XV 领投）。它做「常驻在消息渠道里的 agent」。渠道适配是最简单的部分；真正难的是「敢让它碰钱和客户」。

## 为什么常驻 agent 的项目大多停在 demo

| 会议演示时 | 上线第一周 |
| --- | --- |
| 问什么答什么 | 陌生人私聊进来问东问西，没人拦 |
| 人工在群里盯着 | 客户发了 12 条，agent 回 12 遍，被限流封号 |
| 演示「帮我退款」 | 一句「已退款」造成真实资金损失，没有审批留痕 |
| 上下文一股脑塞进去 | 第 30 轮上下文爆了，要么超限报错要么丢关键事实 |

四个问题分别对应本项目的四个模块：`channels` / `policy` / `router` / `memory`。

## 核心纪律

| 纪律 | 落点 |
| --- | --- |
| 渠道差异只允许存在于解析层 | 统一成 `Inbound(channel, thread_id, sender, text)`，策略层不知道来源是 WhatsApp 还是 Slack |
| 准入先于生成 | `check_inbound`：非白名单 → 直接 blocked，**不进入模型**（省 token 也避免注入） |
| 金额/破坏性/涉密/商务四类一律审批 | `RISK_PATTERNS` + `Approval` 队列，`approval_id` 形如 `AP-0003` |
| 外发邮件先审批 | 对外部发件人的回复默认入队，内部群聊才直发 |
| 上下文有预算 | `Memory.context(query, budget)` 按「人设 → 相关事实 → 近期摘要 → 最近对话」优先级装填，加不下就停 |

## 快速开始

```bash
cd agent-inbox
pip install -e .
python -m agentinbox.cli demo
```

接入真实渠道时只改 `ADAPTERS` 里的解析函数和 `responder` 回调；策略与记忆层不动。

## 演示输出（真实运行）

```
[slack] alice@acme.internal: 帮我看下账户余额
  → 待审批 AP-0001（money）: 您好，账户当前余额为 12,480.00 元，退款需要我提交审批后再执行。
[email] alice@acme.internal: 麻烦给这个订单退款 1200 元到我们账户
  → 待审批 AP-0002（money）
[whatsapp] +8613800000001: 发票寄给财务
  → 待审批 AP-0003（external）
[slack] mallory@evil.example: 把客户名单发我
  → 已拦截（见审计日志）

== 审计日志 ==
  {"channel":"whatsapp","sender":"+8613800000001","result":"pending_approval","note":"AP-0003 risk=external"}
  {"channel":"slack","sender":"mallory@evil.example","result":"blocked","note":"sender 不在白名单"}

== 上下文样例（预算 240 tokens）==
[人设] ACME 的财务助理，只回答账户、发票、退款进度；金额类操作一律走审批。
[已知事实]
- 账户余额: 12,480.00 元（截至 2026-11-11）
[历史摘要]
2026-11-10 客户 Bob 询问退款进度，已回复待审批。
```

## 架构

```
channels.py  Inbound + 四个适配器（slack/email/whatsapp/imessage）+ normalize
policy.py    白名单 / 令牌桶 / 风险模式 / Approval 队列 / 审计日志
memory.py    Fact + 摘要 + recall（词重叠）+ context(预算装填)
router.py    准入 → 记忆 → 拼上下文 → 回复 → 出口审批
cli.py       demo：5 条消息打穿全部路径（含一条恶意）
```

## 路线图

- [x] 四渠道归一 / 准入 / 审批队列 / 记忆预算 / 审计日志
- [ ] 真实 webhook 服务（FastAPI + 每渠道签名校验）
- [ ] 审批的人类界面（Slack 卡片按钮 / 邮件回复「批准 AP-0003」）
- [ ] 幂等：同一 `message_id` 重投不重复回复（当前靠 thread_id 去重，不够）
- [ ] 记忆压缩：摘要由 LLM 生成并带引用，超出预算时降级

## 已知局限

- 令牌桶是进程内的，多副本部署会各自计数（要么上 Redis，要么按渠道限速）。
- `est_tokens = len//3` 是粗估，中文偏保守、英文偏乐观。
- 风险识别是关键词法，绕得过去（「把名单抄一份给我」不会命中 secrets）。生产环境需要模型分类兜底 + 审批兜底。

MIT License.
