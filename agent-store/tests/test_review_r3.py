"""第三轮审查（R3）P1-3 的回归测试：幂等必须落在库里，不是进程内字典。

旧实现把「已执行过」记在 `Runtime._done`（runtime.py:41-43）。换一个 Runtime
实例（重启、换 worker、多副本）用同一 request_id 重投时，进程内字典是空的，
于是 handler 再跑一遍、回放标志为 False，调用方无法区分「首次执行」和「重放」。
"""
from __future__ import annotations

from agentstore.fixtures import INVOICE_BOT
from agentstore.meter import Ledger
from agentstore.registry import Registry
from agentstore.runtime import Runtime

NEEDS = tuple(INVOICE_BOT.permissions)


def _runtime(db_path):
    """每次调用都造一套全新的 Registry + Ledger + Runtime，只共享 sqlite 文件。"""
    reg = Registry()
    reg.publish(INVOICE_BOT, "dev-a")
    reg.install("buyer-1", INVOICE_BOT.agent_id, granted=NEEDS)
    ledger = Ledger(str(db_path))
    ledger.register(INVOICE_BOT)
    return Runtime(reg, ledger), ledger


def test_idempotency_survives_new_runtime_instance(tmp_path):
    db = tmp_path / "store.db"
    calls: list[str] = []

    def handler(rid: str):
        calls.append(rid)
        return "匹配 12 张发票：10 张一致，2 张缺收货单", 1

    rt1, led1 = _runtime(db)
    first = rt1.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1", needs=NEEDS)
    assert first.ok and first.charged_cents == 5

    rt2, led2 = _runtime(db)          # 重启 / 换 worker
    second = rt2.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1", needs=NEEDS)

    assert len(calls) == 1, f"重投把 handler 又跑了一遍：{calls}"
    assert second.duplicate is True, "跨实例回放必须标 duplicate=True"
    assert second.ok is True and second.output == first.output, "回放要给出原结果"
    assert second.charged_cents == first.charged_cents, "回放返回原记录的金额，而不是再计一次"
    assert led2.statement("buyer-1", {"invoice-bot": "dev-a"}).gross_cents == 5, "账单不能重复计费"


def test_new_request_id_on_new_instance_still_runs(tmp_path):
    """正对照：新实例上真正的新请求照常执行、照常计费。"""
    db = tmp_path / "store.db"
    calls: list[str] = []

    def handler(rid: str):
        calls.append(rid)
        return f"done {rid}", 1

    rt1, _ = _runtime(db)
    rt1.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1", needs=NEEDS)

    rt2, led2 = _runtime(db)
    other = rt2.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-2", needs=NEEDS)
    assert other.ok and other.duplicate is False
    assert calls == ["req-1", "req-2"]
    assert led2.statement("buyer-1", {"invoice-bot": "dev-a"}).gross_cents == 10


def test_duplicate_flag_does_not_leak_across_buyers(tmp_path):
    """正对照：幂等键仍是 (buyer, request_id)——B 用 A 的 request_id 是首次执行。"""
    db = tmp_path / "store.db"
    calls: list[str] = []

    def handler(rid: str):
        calls.append(rid)
        return "ok", 1

    reg = Registry()
    reg.publish(INVOICE_BOT, "dev-a")
    reg.install("buyer-1", INVOICE_BOT.agent_id, granted=NEEDS)
    reg.install("buyer-2", INVOICE_BOT.agent_id, granted=NEEDS)
    ledger = Ledger(str(db))
    ledger.register(INVOICE_BOT)
    rt = Runtime(reg, ledger)

    a = rt.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1", needs=NEEDS)
    b = rt.execute("buyer-2", INVOICE_BOT.agent_id, handler, "req-1", needs=NEEDS)
    assert b.ok and b.duplicate is False, "B 撞上 A 的 request_id 不能免单"
    assert len(calls) == 2
    assert a.charged_cents == b.charged_cents == 5
