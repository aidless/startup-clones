"""filing-lens 的本地演示服务。

它只做一件事：把库里已经验证过的链路（解析 → BM25 → XBRL → 拒答契约）暴露成一个
可以被点开的界面。没有数据库、没有用户系统、没有缓存层——演示用的东西不该有第二套逻辑。

启动：
    python3 app/server.py                # 打开 http://127.0.0.1:8765
    python3 app/server.py --port 9000
    FILINGLENS_DATA=/path/to/data python3 app/server.py

数据来自 `scripts/fetch_edgar.py` 下载到 `data/` 的文件（默认 Apple FY2026 与 MSFT FY2026）。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from filinglens import corpus, ingest  # noqa: E402
from filinglens.corpus import Filing  # noqa: E402

DATA_DIR = Path(os.environ.get("FILINGLENS_DATA", ROOT / "data"))
# /api/ingest 会往磁盘写文件（可覆盖真实 10-K）。演示服务默认只读，
# 写入必须显式配 token；没配 = 关死，而不是「谁都能写」。
INGEST_TOKEN = os.environ.get("FILINGLENS_INGEST_TOKEN", "")
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="filing-lens", docs_url="/api/docs")

logger = logging.getLogger(__name__)


_CACHE: dict[str, Filing] = {}


def configure(data_dir: str | Path) -> None:
    """测试用：换数据目录并清掉已解析的缓存。"""
    global DATA_DIR
    DATA_DIR = Path(data_dir)
    _CACHE.clear()


def scan() -> list[dict]:
    """列出 data/ 下所有可用的 10-K 文件。"""
    return corpus.discover(DATA_DIR)


def load(cik: str) -> Filing:
    if cik in _CACHE:
        return _CACHE[cik]
    try:
        filing = corpus.load(DATA_DIR, cik)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"{exc}；先跑 scripts/fetch_edgar.py 或 POST /api/ingest") from exc
    except ingest.IngestError as exc:
        # 非法 tag（含 glob 元字符、路径分隔符）是调用方输入错误，不是服务端故障
        raise HTTPException(400, str(exc)) from exc
    _CACHE[cik] = filing
    return filing


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/filings")
def filings() -> JSONResponse:
    return JSONResponse({"data_dir": str(DATA_DIR), "filings": scan()})


@app.post("/api/ingest")
def ingest_one(body: dict, request: Request) -> JSONResponse:
    """把任意 CIK 或任意 10-K URL 弄进 data/，然后立刻可问。

    这是"支持任意公司"的唯一入口——页面上的下拉框只列 data/ 里已有的文件，
    真正的扩展靠这里。
    """
    if not INGEST_TOKEN:
        raise HTTPException(403, "写入接口未启用：启动时设置 FILINGLENS_INGEST_TOKEN 才允许 POST /api/ingest")
    if request.headers.get("X-Ingest-Token") != INGEST_TOKEN:
        raise HTTPException(403, "X-Ingest-Token 缺失或不正确")

    cik, url = (body or {}).get("cik"), (body or {}).get("url")
    if not cik and not url:
        raise HTTPException(400, "要么给 cik，要么给 url")
    try:
        if url:
            out = ingest.from_url(url, DATA_DIR, facts_url=body.get("facts_url"),
                                  tag=body.get("tag"), period=body.get("period"))
            tag = out["tag"]
        else:
            out = ingest.from_cik(cik, DATA_DIR)
            tag = out["tag"]
    except ingest.IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    _CACHE.pop(tag, None)
    return JSONResponse({"ingested": out, "meta": load(tag).meta()})


@app.get("/api/meta")
def meta(cik: str = Query(..., description="10 位 CIK，例如 0000320193")) -> JSONResponse:
    return JSONResponse(load(cik).meta())


@app.get("/api/ask")
def ask(
    q: str = Query(..., min_length=2, description="自然语言问题，中英文都行"),
    cik: str = Query(..., description="10 位 CIK"),
) -> JSONResponse:
    filing = load(cik)
    resp = filing.answerer.ask(q)
    return JSONResponse({
        "question": q,
        "kind": resp.kind,
        "status": resp.status,
        "text": resp.text,
        "confidence": round(resp.confidence, 3),
        "citations": [{"ref": c.ref, "quote": c.quote, "kind": c.kind} for c in resp.citations],
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # 启动横幅走 logging 而不是 print：这层日志以后要和 uvicorn 的日志一起被重定向/过滤，
    # 混一条裸 print 到 stdout 会绕开任何一层 handler。format 只留消息，保持原来的阅读效果。
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    available = scan()
    if not available:
        logger.error("%s 里没有 10-K 文件。先跑：python3 scripts/fetch_edgar.py", DATA_DIR)
        return 1
    logger.info("数据目录 %s，可用文件 %d 份", DATA_DIR, len(available))
    for f in available:
        logger.info("  CIK %s  期间 %s  XBRL %s", f["cik"], f["period"],
                    "有" if f["has_xbrl"] else "无")
    logger.info("\n打开 http://%s:%d", args.host, args.port)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
