"""SQLite 持久层：一跑一存，保证历史可回溯。

表：runs / answers / mentions。answers 存全文（GEO 的原始证据必须留档，
否则客户问「你凭什么说我没被提到」时无法自证）。
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Answer, Citation, Mention, Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    competitors TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    run_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    citations TEXT NOT NULL,
    PRIMARY KEY (run_id, prompt_id, run_index, model)
);
CREATE TABLE IF NOT EXISTS mentions (
    run_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    brand TEXT NOT NULL,
    position INTEGER NOT NULL,
    char_offset INTEGER NOT NULL,
    sentiment REAL NOT NULL,
    context TEXT NOT NULL,
    run_index INTEGER NOT NULL DEFAULT 0,
    -- 主键必须带 run_index：同一 prompt 的 repeat 次采样是各自独立的观测，
    -- 只按 (run_id, prompt_id, brand) 去重会把 72 条压成 32 条，
    -- `report --run-id` 的份额/位次与 `run` 当时打印的就对不上（实测 34.72% → 34.38%）。
    -- 仍然保留幂等：同一 run 重存（重跑导出/断点续跑）不会把 mention 翻倍。
    PRIMARY KEY (run_id, prompt_id, run_index, brand)
);
CREATE INDEX IF NOT EXISTS idx_mentions_run ON mentions(run_id);
"""


def connect(path: str | Path = "georadar.db") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_run(conn: sqlite3.Connection, run: Run, mentions: list[Mention]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO runs(run_id,brand,category,competitors,provider,created_at) VALUES (?,?,?,?,?,?)",
        (run.run_id, run.brand, run.category, json.dumps(run.competitors, ensure_ascii=False),
         run.provider, run.created_at),
    )
    for a in run.answers:
        conn.execute(
            "INSERT OR REPLACE INTO answers(run_id,prompt_id,run_index,provider,model,text,citations) VALUES (?,?,?,?,?,?,?)",
            (run.run_id, a.prompt_id, a.run_index, a.provider, a.model, a.text,
             json.dumps([c.__dict__ for c in a.citations], ensure_ascii=False)),
        )
    for m in mentions:
        conn.execute(
            "INSERT OR REPLACE INTO mentions(run_id,prompt_id,run_index,brand,position,char_offset,sentiment,context) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run.run_id, m.prompt_id, m.run_index, m.brand, m.position, m.char_offset,
             m.sentiment, m.context),
        )
    conn.commit()


def load_run(conn: sqlite3.Connection, run_id: str) -> tuple[Run, list[Mention]]:
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    run = Run(
        run_id=row["run_id"], brand=row["brand"], category=row["category"],
        competitors=json.loads(row["competitors"]), provider=row["provider"],
        created_at=row["created_at"],
    )
    for r in conn.execute("SELECT * FROM answers WHERE run_id=? ORDER BY prompt_id,run_index", (run_id,)):
        run.answers.append(Answer(
            prompt_id=r["prompt_id"], provider=r["provider"], model=r["model"], text=r["text"],
            citations=[Citation(**c) for c in json.loads(r["citations"])], run_index=r["run_index"],
        ))
    mentions = [Mention(**dict(r)) for r in conn.execute(
        "SELECT prompt_id,run_index,brand,position,char_offset,sentiment,context "
        "FROM mentions WHERE run_id=? ORDER BY prompt_id,run_index,position", (run_id,))]
    return run, mentions


def new_run_id(prefix: str = "run") -> str:
    """秒级时间戳 + 微秒 + 4 位随机后缀。

    只到秒时同秒两次调用得到同一个 run_id（实测 `run-20261113T045212` ×2），
    而 run_id 是主键：后一次会把前一次的 runs 行覆盖掉，历史静默丢失。
    """
    now = datetime.now(timezone.utc)
    return f"{prefix}-{now.strftime('%Y%m%dT%H%M%S')}{now.microsecond:06d}-{secrets.token_hex(2)}"


def delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    """撤销一次没走完的 run（渲染/写文件阶段炸了，库里不该留半份报告）。"""
    with conn:
        conn.execute("DELETE FROM mentions WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM answers WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
