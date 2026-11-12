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
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def add_label(conn: sqlite3.Connection, case_id: str, labeler: str, passed: bool,
              rubric: dict | None = None, rationale: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO labels(case_id,labeler,passed,rubric,rationale,created_at) VALUES (?,?,?,?,?,?)",
        (case_id, labeler, int(passed), json.dumps(rubric or {}, ensure_ascii=False), rationale,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()


def load_labels(conn: sqlite3.Connection, labeler: str) -> dict[str, bool]:
    rows = conn.execute(
        "SELECT case_id, passed FROM labels WHERE labeler=? ORDER BY case_id", (labeler,)
    ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def latest_verdicts(conn: sqlite3.Connection, verdicts: list) -> None:
    for v in verdicts:
        add_label(conn, v.case_id, "judge", v.passed,
                  {d.name: d.score for d in v.details},
                  f"score={v.score:.3f} threshold={v.threshold}")
