"""他山之石第二轮：filing-lens 的事实库连接要能等锁（console 多线程读同一个文件库）。

来源 https://sqlite.org/wal.html §1/§9。:memory: 上跳过 WAL。
"""
from __future__ import annotations

from filinglens.facts import load_companyfacts

PAYLOAD = {"cik": "1", "entityName": "X", "facts": {}}


def test_file_database_uses_wal_and_waits_for_locks(tmp_path):
    conn = load_companyfacts(PAYLOAD, tmp_path / "facts.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_memory_database_still_works():
    conn = load_companyfacts(PAYLOAD)
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    assert conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 0
