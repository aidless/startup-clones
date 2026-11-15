# 参与开发

这是一个「一个仓库、七个工具」的 monorepo：每个子目录都是能单独 `pip install -e .`
的东西，根目录只放跨项目的契约（`conftest.py` / `pytest.ini` / `Makefile` / `scripts/`）。
项目之间**互相不 import**——拆开任何一个，其余六个照常工作。

## 上手

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e "agent-inbox[dev]" -e "agent-store[dev]" -e "audit-loop[dev]" \
            -e "console[dev]" -e "cruxline[dev]" -e "filing-lens[dev]" -e "geo-radar[dev]"
make test     # 七个项目逐个跑
python3 -m pytest   # 或根目录一次跑完（同一套，更快）
make demo     # 六个内核各跑一遍 demo，不需要任何 API key
make e2e      # 端到端：十个阶段跨六个项目真跑
```

`filing-lens` 有一层额外语料：`data/`（22 份真实 10-K，164MB）**不进仓库**。
没有它时相关用例会自动 skip，其余照跑；要跑全量看
[`filing-lens/README.md`](filing-lens/README.md) 的「先跑测试要备好语料」一节。
`make matrix` 只在语料在位时有意义，`make checks`（六项检查的命中率普查）同理。

## 提交前

```bash
python3 -m pytest              # 必须全绿（缺语料时 skip 的那几十条除外）
python3 scripts/e2e.py         # 十个阶段全过
python3 scripts/polish_audit.py # README/边界/CLI/卫生七项判据
```

三条硬要求：

1. **测试先红后绿**。改行为之前先写一条会失败的断言；只加「能过」的测试等于没测。
   注入违规必须能让它红（`python3 -m pytest tests/test_ci_hooks.py -q` 里有现成的例子）。
2. **不许有 mock 掉的断言**。这里所有测试都跑真实现、真文件、真子进程；需要外部
   服务时用 fixtures 里的离线样本（`filinglens/fixtures.py`、`cruxline/data/traces.jsonl`）。
3. **文档与实现同一次提交**。README 里的数字、命令、阈值都要能在当前代码上复现；
   只改实现不改文档，等于给下一个人埋一个假事实。

## 代码风格

- Python ≥ 3.11，标准库优先。依赖只有四个：`httpx`（抓 SEC/模型）、
  `beautifulsoup4`+`lxml`（解析 10-K HTML）、`openpyxl`（审计底稿）、`fastapi`+`uvicorn`（演示台）。
- 命名、注释、日志用中文，代码标识符用英文。注释写「为什么」，不写「这行在做什么」。
- 每个模块顶部有一段 docstring 说明边界：什么做了、什么**不做**。已知限制写在
  README 的「已知边界」小节里，带 `文件:行`。
- 不引入 `try/except: pass`、不吞异常；错误要带上下文（哪个文件、哪个字段、期望什么）。

## 安全问题

发现凭据泄露、路径穿越、SSRF、XXE 一类问题，先别开公开 issue，直接发给维护者。
`filing-lens` 会主动去抓 SEC 的文件，所有抓取只允许 HTTPS + SEC 域名
（`filinglens/ingest.py:72 _check_url`），这条边界不要在 PR 里放宽。

## 许可证

MIT，见 [`LICENSE`](LICENSE)。提交即表示你同意以同一许可发布。
