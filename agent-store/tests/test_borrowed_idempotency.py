"""他山之石第二轮：Idempotency-Key 的指纹语义 + sqlite 的 busy_timeout / WAL。

来源：
- draft-ietf-httpapi-idempotency-key-header-08 §2.2「键必须唯一，且不得用于不同 payload
  的请求」、§2.4「指纹由请求 payload 生成」、§2.7「键被复用到不同 payload → 422」。
- https://sqlite.org/wal.html §1/§9：WAL 让读不阻塞写，但仍可能返回 SQLITE_BUSY，
  所以还要 busy_timeout。

现状（会红）：
- 同一个 (buyer, request_id) 换一个 agent_id 重投，旧实现照样回放上一次的结果 ——
  调用方拿到的是「另一次请求的答案」，还标着 duplicate=True。
- Ledger 用默认 sqlite 设置（busy_timeout=0、journal_mode=delete），第二个写者立刻
  抛 database is locked，而不是等一会儿。
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from agentstore.fixtures import INVOICE_BOT
from agentstore.meter import Ledger
from agentstore.registry import Registry
from agentstore.runtime import Runtime

NEEDS = tuple(INVOICE_BOT.permissions)


def _runtime(db_path):
    reg = Registry()
    reg.publish(INVOICE_BOT, "dev-a")
    reg.install("buyer-1", INVOICE_BOT.agent_id, granted=NEEDS)
    ledger = Ledger(str(db_path))
    ledger.register(INVOICE_BOT)
    return Runtime(reg, ledger), ledger


def _handler(seen: list[str]):
    def h(rid: str):
        seen.append(rid)
        return "匹配 12 张发票", 1
    return h


def test_same_key_with_a_different_agent_is_a_conflict(tmp_path):
    """键复用到另一个 agent 的请求上，必须报冲突，不能把上一个结果当成这次的答案。"""
    db = tmp_path / "store.db"
    seen: list[str] = []
    rt, _ = _runtime(db)
    first = rt.execute("buyer-1", INVOICE_BOT.agent_id, _handler(seen), "req-1", needs=NEEDS)
    assert first.ok

    # 同一个键，但请求的 agent 变了（真实场景：客户端复用了一个 UUID）
    rt2, _ = _runtime(db)
    second = rt2.execute("buyer-1", "another.agent", _handler(seen), "req-1", needs=NEEDS)

    assert second.ok is False, "键被复用仍返回成功，调用方拿到了别人的结果"
    assert second.error.startswith("idempotency_conflict"), second.error
    assert second.duplicate is False
    assert seen == ["req-1"], "冲突的请求不该执行 handler"


def test_same_key_with_more_usage_is_a_conflict(tmp_path):
    """同一个键但 tokens 不同：计费口径变了，同样是「不同 payload」。"""
    db = tmp_path / "store.db"
    seen: list[str] = []
    rt, _ = _runtime(db)
    rt.execute("buyer-1", INVOICE_BOT.agent_id, _handler(seen), "req-1", needs=NEEDS, tokens=100)

    rt2, _ = _runtime(db)
    again = rt2.execute("buyer-1", INVOICE_BOT.agent_id, _handler(seen), "req-1",
                        needs=NEEDS, tokens=900)
    assert again.ok is False
    assert again.error.startswith("idempotency_conflict")


def test_identical_retry_still_replays(tmp_path):
    """正对照：一模一样的重投必须照旧回放，且不再执行 handler。"""
    db = tmp_path / "store.db"
    seen: list[str] = []
    rt, _ = _runtime(db)
    rt.execute("buyer-1", INVOICE_BOT.agent_id, _handler(seen), "req-1", needs=NEEDS, tokens=100)

    rt2, _ = _runtime(db)
    same = rt2.execute("buyer-1", INVOICE_BOT.agent_id, _handler(seen), "req-1",
                       needs=NEEDS, tokens=100)
    assert same.ok and same.duplicate is True
    assert seen == ["req-1"]


def test_ledger_waits_for_a_lock_instead_of_failing(tmp_path):
    """busy_timeout：另一个连接持锁时，第二个写者应该等，而不是立刻 database is locked。

    写者必须在自己的线程里建自己的连接 —— sqlite3 默认 `check_same_thread=True`，
    跨线程复用同一个 Connection 会先抛 ProgrammingError，测不到锁行为。
    """
    db = tmp_path / "store.db"
    led1 = Ledger(str(db))
    led1.conn.execute("BEGIN IMMEDIATE")

    errors: list[Exception] = []

    def writer():
        led2 = Ledger(str(db))                       # 每条线程一个连接，用完即关
        try:
            led2.record("buyer-1", INVOICE_BOT.agent_id, INVOICE_BOT.version,
                        "req-lock", 1, 5)
        except Exception as exc:                     # noqa: BLE001
            errors.append(exc)
        finally:
            led2.conn.close()

    t = threading.Thread(target=writer)
    t.start()
    t.join(0.4)                                      # 应该还卡在等锁
    assert t.is_alive(), "写者没等锁就返回了：busy_timeout 没生效"
    led1.conn.commit()
    t.join(6)
    assert not errors, errors
    assert led1.replay("buyer-1", "req-lock") is not None


def test_ledger_uses_wal_for_file_databases(tmp_path):
    """WAL：读不阻塞写。file: 数据库必须真的切过去（:memory: 上不适用）。"""
    led = Ledger(str(tmp_path / "store.db"))
    assert led.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert led.conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_memory_database_still_works(tmp_path):
    """正对照：`:memory:` 上 WAL 不可用（每个连接一个库），不能因此报错。"""
    led = Ledger()
    led.record("buyer-1", INVOICE_BOT.agent_id, INVOICE_BOT.version, "req-mem", 1, 5)
    assert led.replay("buyer-1", "req-mem") is not None
