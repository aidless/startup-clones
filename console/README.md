# console — 六个工具的统一演示台

一个 FastAPI 进程 + 一个页面，把六个项目各自的链路原样暴露出来。**没有为演示另写逻辑**：
每个面板调的都是库里已经在跑的函数。

```bash
python3 app.py --port 8800     # → http://127.0.0.1:8800
```

## 六个面板

| 面板 | 背后调的东西 | 页面上必须看到 |
|---|---|---|
| geo-radar | `MockProvider` 采样 + `extract.find_mentions` + `metrics.brand_stats` | 份额表（总和闭合到 100%）、抽样的提示词 |
| filing-lens | `edgar.parse` → `BM25Index` → `Answerer.ask` | 正文、状态徽章、段落级出处；拒答时出处为空 |
| audit-loop | `auditloop.cli.build_run` | 程序×认定表 + 例外清单（high 标红） |
| cruxline | `Judge.score_all` + `calibrate` + `regress.diff` | 硬否决标签、kappa、版本回归结论 |
| agent-inbox | `Policy` + `Memory` + `Router` | 拦截/已发送/待审批、审批队列、审计日志 |
| agent-store | `Registry` + `Runtime` + `Ledger.statement` | 目录、调用结果（含被拦与重投）、分成账单 |

## 为什么值得单独做一个 app

1. **一次跑通六条链路**：任何一条断掉，页面就是空白——这比六个 CLI 更容易发现回归。
2. **把契约显性化**：拒答的答案卡片上「没有引用」必须肉眼可见；被拦的调用旁边必须写清
   `permission_denied`；重投必须标「未重复计费」。这些都是库里已有的断言，页面上再验一遍。
3. **演示用假模型是安全的**：GEO 面板用 `MockProvider`（确定性），不烧 token、不联网；
   10-K 面板读本地 `data/`，不碰 SEC。

## 已知局限

- 无鉴权、无并发保护，只在本机演示用。
- filing 面板的 `Answerer` 缓存在进程内，`data/` 里新增文件需要重启。
- GEO 面板故意用假模型：真实份额结论见 `geo-radar/README.md` 的强模型对照表。
