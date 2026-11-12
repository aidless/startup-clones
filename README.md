# startup-clones

六个 **可运行的内核**，分别对应 2026 年 10–11 月刚融资的六家美国公司的产品形态。目的不是复制产品，而是把「这类产品为什么能卖钱」拆成可验证的代码：每条商业纪律都对应一个测试。

**71 个测试，0 个 mock 掉的断言，全部离线可跑。**

```bash
git clone <this-repo> && cd startup-clones
make test      # 六个子项目逐个跑，共 71 passed
make demo      # 六个 demo 各跑一遍（无需任何 API key）
```

## 六个项目

| 目录 | 对标（融资事实） | 一句话内核 | 测试 |
| --- | --- | --- | --- |
| [`geo-radar/`](geo-radar) | The Prompting Company · 2026-11-03 $6.5M 种子 | 测「AI 推荐里有没有你」：提示词生成 → 多模型跑 → 提及抽取 → 站位报告 | 10 |
| [`filing-lens/`](filing-lens) | Finpilot · 2026-11-04 $10M A（Lobby Capital + Madrona） | 用大白话问上市公司财报：10-K 分段 → BM25 → XBRL 数字，**没有引用就不回答** | 15 |
| [`audit-loop/`](audit-loop) | Clark · 2026-11-02 $11M 种子（Touring Capital） | 给事务所的审计程序内核：银行调节/账龄/截止测试 → 例外清单 + 可归档 Excel 底稿 | 11 |
| [`cruxline/`](cruxline) | Crux Labs · 2026-10-30 $6M+ 种子 | 把「专家觉得这算做好了」变成 rubric + kappa 校准 + 版本回归门禁，**致命项一票否决** | 16 |
| [`agent-inbox/`](agent-inbox) | Inkbox · 2026-11-09 $5.3M 种子（Peak XV） | 常驻消息渠道的 agent：准入 → 审批队列 → 预算化记忆 → 全程审计 | 8 |
| [`agent-store/`](agent-store) | Cowboy · 2026 年 $5M 种子 | agent 商店：不可变版本 + 最小授权 + 幂等计量 + 分成账单 | 11 |


## 真实数据状态

夹具只能证明代码能跑。每个项目对「真实世界」的接入程度不同，这里如实标：

| 项目 | 真实数据 | 现在的可信度 |
| --- | --- | --- |
| filing-lens | Apple / Microsoft FY2026 10-K + XBRL（`scripts/fetch_edgar.py`） | 8/8 真实问答回归；6 个真实缺陷已修 |
| audit-loop | 同上 XBRL 的 8–9 年财务序列（`scripts/real_analytics.py`） | Apple 报 2 条例外、Microsoft 零例外 |
| agent-inbox | SEC CORRESP 往来函件（`scripts/fetch_sec_corresp.py`） | 3 封真实函件、1 线程、2 条缺口如实报出 |
| cruxline | 60 条真实 dsh 会话轨迹（`scripts/export_dsh_traces.py`） | 58/60 通过；2 条失败是真缺陷 |
| agent-store | 16 个真实 MCP server 清单（`scripts/fetch_mcp_servers.py`） | 16/16 无权限声明；2 个假阳性已修 |
| geo-radar | 本机 3 小模型 + Magpie 3 强模型 × 8 问（`scripts/real_geo.py`） | 小模型把 Expensify 排第一、强模型一致排 Ramp；跨档位混算等于造假 |

`data/` 全部 gitignore —— 仓库里只有代码与测试，原始语料用脚本按需拉回。

## 抄什么，不抄什么

**抄**：信息架构（左侧导航到底有哪几项）、工作流顺序（先上传再抽取再确认）、定价页的分档逻辑（按次 / 按 token / 按月）、onboarding 的第一个成功时刻、ROI 话术的锚点。

**不抄**：品牌与商标、任何 benchmark 数字（复现不了就别写进 README）、客户 logo、专有数据集。

**必须自建**：数据清洗规则（脏 Excel 长什么样只有你知道）、垂直判断逻辑（哪条例外要升级为「需调整」）、集成（客户的 ERP / 邮箱 / 工单系统）。

**三条硬约束**（开工前先查，不是上线前）：USPTO 按公司名搜 provisional 专利；商标查同类别；数据合规——B 端采购的第一道门是 SOC 2 Type II，没有它连 POC 都排不上。

## 融资信号怎么用

拿到 A/B 轮的公司 12 个月内会做三件事：涨价、把产品往企业版推、放弃客单价低的中小客户。

这三件事同时意味着一个窗口：**「同样的功能 + 更窄的场景 + 更低的价格 + 愿意接小客户」**。六个项目都按这个窗口设计——每个 README 的「已知局限」写的就是大厂不会做、但小客户天天骂的那部分。

## 关于「抄」的边界

这些代码是各自领域**公开知识的工程化重组**：BM25 是 1994 年的论文，XBRL 是 SEC 的公开规范，审计程序写在准则里，kappa 是 1960 年的统计量。没有一行来自上面那些公司的私有代码。

真正不可复制的是他们的数据和客户合同，所以本项目每个目录都刻意做了同一件事：**用夹具证明机制成立，并明确写出「离产品还差什么」**。

## 许可

MIT。

## 界面

filing-lens 带一个本地演示页（FastAPI + 单页 HTML，无前端构建）：

```bash
cd filing-lens && python3 app/server.py      # → http://127.0.0.1:8765
# 或
make serve
```

页面做三件事：选一份已下载的 10-K、提问、看答案卡片。
卡片上必须同时出现三样东西——**回答正文、状态徽章、段落级出处**。
没出处就没有答案（`insufficient_evidence`），这是库里已经在守的契约，界面上也一样。
