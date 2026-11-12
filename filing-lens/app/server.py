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
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from filinglens import answer as answer_mod  # noqa: E402
from filinglens import edgar, facts, index  # noqa: E402

DATA_DIR = Path(os.environ.get("FILINGLENS_DATA", ROOT / "data"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="filing-lens", docs_url="/api/docs")


class Filing:
    """一份已解析的 10-K：文本块 + XBRL 连接 + 检索索引都在这里。"""

    def __init__(self, cik: str, html_path: Path, facts_path: Path | None):
        self.cik = cik
        self.doc = html_path.stem
        html = html_path.read_text(errors="ignore")
        _, self.chunks, self.tables = edgar.parse(html, doc=self.doc)
        self.index = index.BM25Index().add(self.chunks)
        self.conn: sqlite3.Connection | None = None
        if facts_path and facts_path.exists():
            payload = json.loads(facts_path.read_text())
            self.conn = facts.load_companyfacts(payload)
        self.answerer = answer_mod.Answerer(self.chunks, self.conn)

    @property
    def periods(self) -> str:
        # 文件名形如 0000320193_10k_2026-09-26.htm，期间就是从文件名里来的
        parts = self.doc.split("_")
        return parts[-1] if len(parts) >= 3 else "unknown"

    def meta(self) -> dict:
        return {
            "cik": self.cik,
            "doc": self.doc,
            "period": self.periods,
            "sections": len({c.item for c in self.chunks}),
            "chunks": len(self.chunks),
            "tables": len(self.tables),
            "has_xbrl": self.conn is not None,
        }


_CACHE: dict[str, Filing] = {}


def configure(data_dir: str | Path) -> None:
    """测试用：换数据目录并清掉已解析的缓存。"""
    global DATA_DIR
    DATA_DIR = Path(data_dir)
    _CACHE.clear()


def scan() -> list[dict]:
    """列出 data/ 下所有可用的 10-K 文件。"""
    out = []
    for p in sorted(DATA_DIR.glob("*_10k_*.htm")):
        cik = p.name.split("_")[0]
        facts_path = DATA_DIR / f"{cik}_facts.json"
        out.append({"cik": cik, "period": p.name.split("_")[-1].replace(".htm", ""),
                    "has_xbrl": facts_path.exists()})
    return out


def load(cik: str) -> Filing:
    if cik in _CACHE:
        return _CACHE[cik]
    hits = sorted(DATA_DIR.glob(f"{cik}_10k_*.htm"))
    if not hits:
        raise HTTPException(404, f"data/ 下没有 CIK {cik} 的 10-K，先跑 scripts/fetch_edgar.py")
    facts_path = DATA_DIR / f"{cik}_facts.json"
    filing = Filing(cik, hits[-1], facts_path if facts_path.exists() else None)
    _CACHE[cik] = filing
    return filing


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/filings")
def filings() -> JSONResponse:
    return JSONResponse({"data_dir": str(DATA_DIR), "filings": scan()})


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

    available = scan()
    if not available:
        print(f"{DATA_DIR} 里没有 10-K 文件。先跑：python3 scripts/fetch_edgar.py")
        return 1
    print(f"数据目录 {DATA_DIR}，可用文件 {len(available)} 份")
    for f in available:
        print(f"  CIK {f['cik']}  期间 {f['period']}  XBRL {'有' if f['has_xbrl'] else '无'}")
    print(f"\n打开 http://{args.host}:{args.port}")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
