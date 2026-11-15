"""他山之石第二轮：geo-radar 的 sqlite 连接要能等锁、读写不互堵。

来源 https://sqlite.org/wal.html §1（WAL 读不阻塞写）、§9（WAL 下仍可能 SQLITE_BUSY，
所以要 busy_timeout）。:memory: 上每个连接是各自的库，WAL 无意义，必须跳过而不是报错。
"""
from __future__ import annotations

from georadar.store import connect


def test_file_database_uses_wal_and_waits_for_locks(tmp_path):
    conn = connect(tmp_path / "geo.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_memory_database_still_works(tmp_path):
    conn = connect(":memory:")
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
