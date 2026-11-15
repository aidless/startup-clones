# console — 六个工具的统一演示台

一个 FastAPI 进程 + 一个页面，把六个项目各自的链路原样暴露出来。每个面板调的都是库里
已经在跑的函数；**但场景数据（消息、价格、调用序列）是本文件内联的副本**，不是从各项目 CLI
的 demo 里 import 的——CLI 改了 demo 场景，这些面板不会跟着变（见 `app.py:159-265`）。

## 快速开始

```bash
cd console
python3 app.py --port 8800        # 打开 http://127.0.0.1:8800
python3 -m pytest -q              # 12 passed（含真正的跨线程竞态回归：8 线程 × 50 次）
```

命令行验活（不用浏览器也能确认六个面板都活着）：

```bash
for p in projects geo filing audit crux inbox store; do
  printf '%-8s ' "$p"; curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' "http://127.0.0.1:8800/api/$p"
done
```

依赖只有 `fastapi` 与 `uvicorn`（`pyproject.toml` 里声明）；六个子项目的路径由 `app.py`
的 `ROOT`（`__file__` 推导）绝对化，所以**可以从任意目录启动**，只要同级目录里要有那六个项目。

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

## 错误响应是问题文档

按 [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)，错误一律返回
`application/problem+json`，四个成员 `type` / `title` / `status` / `detail` 齐全，
`status` 与 HTTP 状态码一致；参数校验失败的逐条错误放在 `errors` 扩展里：

```bash
curl -s 'http://127.0.0.1:8800/api/filing?cik=not-a-cik' -i | head -4
# HTTP/1.1 400 Bad Request
# content-type: application/problem+json
```

**「本地没这份 10-K」不是错误**：那是正常状态，仍是 `200` + `{"status": "no_data", …}`，
面板要在卡片里就地解释（「先跑 fetch_edgar.py」），不能弹成红色报错。

## 已知局限

- 无鉴权，只在本机演示用。
- filing 面板的 `Answerer` **按线程**缓存（sqlite 连接不跨线程共享，见 `app.py:86-113`）：
  同一线程内复用，`data/` 里新增文件需要重启；进程内最多每个工作线程解析一次 10-K。
- 无请求级配额：20 个并发冷启动请求会各解析一遍 10-K（实测最大 63 s）。
- GEO 面板故意用假模型：真实份额结论见 `geo-radar/README.md` 的强模型对照表。
