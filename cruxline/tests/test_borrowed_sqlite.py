"""他山之石第二轮：cruxline 的标注库连接要能等锁（多人同时标同一批用例）。

来源 https://sqlite.org/wal.html §1/§9。:memory: 上跳过 WAL。
"""
from __future__ import annotations

from cruxline.store import connect


def test_file_database_uses_wal_and_waits_for_locks(tmp_path):
    conn = connect(str(tmp_path / "labels.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_memory_database_still_works():
    conn = connect(":memory:")
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    assert conn.execute("SELECT count(*) FROM labels").fetchone()[0] == 0
