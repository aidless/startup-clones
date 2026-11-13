"""一份已解析的 10-K。

`Filing` 原本写在 `app/server.py` 里，但基准脚本也要用它——那就意味着同一个类会被抄成
两份，而两份一定会漂移（服务改了阈值、脚本没改，基准就开始测一个不存在的产品）。
所以它在这里：只有文本、索引、XBRL 连接、答案器四样东西，不依赖任何 web 框架。
"""

from __future__ import annotations

import glob
import json
import sqlite3
from pathlib import Path

from . import answer as answer_mod
from . import edgar, facts, index
from .ingest import safe_component


class Filing:
    """一份已解析的 10-K：文本块 + XBRL 连接 + 检索索引都在这里。"""

    def __init__(self, cik: str, html_path: Path, facts_path: Path | None = None):
        self.cik = cik
        self.path = Path(html_path)
        self.doc = self.path.stem
        html = self.path.read_text(errors="ignore")
        self.sections, self.chunks, self.tables = edgar.parse(html, doc=self.doc)
        self.index = index.BM25Index().add(self.chunks)
        self.conn: sqlite3.Connection | None = None
        self.facts_payload: dict | None = None
        if facts_path and Path(facts_path).exists():
            self.facts_payload = json.loads(Path(facts_path).read_text())
            self.conn = facts.load_companyfacts(self.facts_payload)
        self.answerer = answer_mod.Answerer(self.chunks, self.conn)

    @property
    def period(self) -> str:
        # 文件名形如 0000320193_10k_2026-09-26.htm，期间就是从文件名里来的
        parts = self.doc.split("_")
        return parts[-1] if len(parts) >= 3 else "unknown"

    def meta(self) -> dict:
        return {
            "cik": self.cik,
            "doc": self.doc,
            "period": self.period,
            "sections": len({c.item for c in self.chunks}),
            "chunks": len(self.chunks),
            "tables": len(self.tables),
            "has_xbrl": self.conn is not None,
        }


def discover(data_dir: str | Path) -> list[dict]:
    """列出 data/ 下所有可用的 10-K。tag 可能是 CIK，也可能是 url 摘要。"""
    out = []
    for p in sorted(Path(data_dir).glob("*_10k_*.htm")):
        tag = p.name.split("_")[0]
        out.append({"tag": tag, "cik": tag, "period": p.name.split("_")[-1].replace(".htm", ""),
                    "path": str(p), "html_kb": round(p.stat().st_size / 1024),
                    "has_xbrl": (Path(data_dir) / f"{tag}_facts.json").exists()})
    return out


def load(data_dir: str | Path, tag: str) -> Filing:
    """按 tag 取一份 10-K。

    tag 必须先收成单段再做文件名匹配：原实现直接 `glob(f"{tag}_10k_*.htm")`，
    `tag="*"` 会把别家公司的文件返回（`GET /api/meta?cik=*` 因此以 200 返回任意文件）。
    """
    data_dir = Path(data_dir)
    tag = safe_component(tag, "tag")
    hits = sorted(data_dir.glob(glob.escape(tag) + "_10k_*.htm"))
    if not hits:
        raise FileNotFoundError(f"{data_dir} 下没有 {tag} 的 10-K")
    facts_path = data_dir / f"{tag}_facts.json"
    return Filing(tag, hits[-1], facts_path if facts_path.exists() else None)
