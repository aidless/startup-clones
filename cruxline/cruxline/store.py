"""标注与判定落库（SQLite）。

两条硬要求：
- 人判和机判分表存、都带 labeler —— 否则事后无法重建一致性证据；
- 判定不可覆盖（INSERT 保留历史），只有显式 supersede 才换新行。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS labels (
    case_id TEXT NOT NULL, labeler TEXT NOT NULL, passed INTEGER NOT NULL,
    rubric TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, labeler, created_at)
);
CREATE INDEX IF NOT EXISTS idx_labels_case ON labels(case_id);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    # 等待锁 + WAL：两人同时标同一批用例时，第二个写者应等 5 秒而不是立刻
    # `database is locked`；WAL 让读不阻塞写（https://sqlite.org/wal.html §1/§9）。
    # `:memory:` 每个连接一个库，WAL 无意义，跳过。
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def add_label(conn: sqlite3.Connection, case_id: str, labeler: str, passed: bool,
              rubric: dict | None = None, rationale: str = "") -> None:
    conn.execute(
        # INSERT OR IGNORE 而非 OR REPLACE：主键含 created_at，一旦时间戳撞上，
        # REPLACE 会静默覆盖先写的那条（同秒先 True 后 False 只剩 False，历史消失）。
        # 判定本不可覆盖，撞上了宁可丢新行也不改写已有证据。
        "INSERT OR IGNORE INTO labels(case_id,labeler,passed,rubric,rationale,created_at) VALUES (?,?,?,?,?,?)",
        (case_id, labeler, int(passed), json.dumps(rubric or {}, ensure_ascii=False), rationale,
         # 秒级精度下同秒两次标注主键相同 → 后者覆盖前者。微秒足够拉开。
         datetime.now(timezone.utc).isoformat(timespec="microseconds")),
    )
    conn.commit()


def load_labels(conn: sqlite3.Connection, labeler: str) -> dict[str, bool]:
    rows = conn.execute(
        # ORDER BY created_at：同一 case 有多条历史时，后面的覆盖前面的 —— 取最新判定
        "SELECT case_id, passed FROM labels WHERE labeler=? ORDER BY case_id, created_at", (labeler,)
    ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def latest_verdicts(conn: sqlite3.Connection, verdicts: list) -> None:
    for v in verdicts:
        add_label(conn, v.case_id, "judge", v.passed,
                  {d.name: d.score for d in v.details},
                  f"score={v.score:.3f} threshold={v.threshold}")
