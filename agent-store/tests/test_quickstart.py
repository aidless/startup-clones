"""README 的三分钟 quickstart 必须真跑得通：这里把 README 里那串操作原样跑一遍。

顺序就是文档的顺序（不 mock 任何东西，全部走 Registry / Ledger / Runtime 真实 API）：

    quickstart 生成工作区 → 发布 → 最小授权安装 → 带幂等键执行
    → 同键同载荷重放（同一个 execution.id，duplicate=True，不再计费）
    → 同键换载荷（ok=False，error 以 idempotency_conflict 开头）
    → Ledger.replay 读回落库结果

生成器自己的两条契约也在这里钉住：
- 重复执行不覆盖用户改过的文件（打印 skip）；
- 打完必须打印接下来要跑的命令（写文件后静默退出等于没跑通）。
"""
from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import json

from agentstore import cli
from agentstore.manifest import load_manifest
from agentstore.meter import Ledger
from agentstore.registry import Registry
from agentstore.runtime import Runtime

AGENT_DIR = ("agents", "hello")
INPUT = "hello agent store"
EXPECTED = "HELLO AGENT STORE"


# --------------------------------------------------------------------------
# 小工具：全部走真实文件系统 + 真实 sqlite 文件，不用 :memory:
# --------------------------------------------------------------------------
def _quickstart(tmp_path, monkeypatch, argv=("quickstart",)):
    monkeypatch.chdir(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    assert code == 0
    return tmp_path / "agentstore-quickstart", buf.getvalue()


def _load_handler(path):
    spec = importlib.util.spec_from_file_location("hello_handler_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installed(ws, db_path: str):
    manifest = load_manifest(ws.joinpath(*AGENT_DIR) / "agent.json")
    needs = tuple(manifest.needs)
    reg = Registry(db_path)
    ledger = Ledger(db_path)
    ledger.register(manifest)
    reg.publish(manifest, "you")
    reg.install("you", manifest.agent_id, granted=needs)
    return manifest, needs, Runtime(reg, ledger), ledger


# --------------------------------------------------------------------------
# 1. 生成物本身
# --------------------------------------------------------------------------
def test_quickstart_writes_a_workspace_that_declares_its_needs(tmp_path, monkeypatch):
    ws, out = _quickstart(tmp_path, monkeypatch)

    for rel in (("agents", "hello", "agent.json"), ("agents", "hello", "handler.py"),
                ("README.md",), ("run.py",)):
        assert ws.joinpath(*rel).is_file(), f"quickstart 没生成 {rel}"

    data = json.loads(ws.joinpath(*AGENT_DIR, "agent.json").read_text(encoding="utf-8"))
    for key in ("id", "name", "version", "needs", "permissions", "price"):
        assert key in data, f"agent.json 缺字段 {key}"
    assert data["id"] == "hello"
    # needs 必须被权限白名单接受（否则走到 publish 就炸）
    manifest = load_manifest(ws.joinpath(*AGENT_DIR, "agent.json"))
    assert set(manifest.needs) <= set(manifest.permissions)

    # 「不许写完文件就静默退出」：三条命令必须打出来
    assert "cd agentstore-quickstart" in out
    assert "python3 run.py" in out
    assert "python3 -m agentstore.cli demo" in out


def test_generated_handler_uppercases_and_is_pure_stdlib(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    handler = ws.joinpath(*AGENT_DIR, "handler.py")

    monkeypatch.delenv("AGENTSTORE_INPUT", raising=False)
    module = _load_handler(handler)
    output, units = module.run("req-x")
    assert output == EXPECTED
    assert units == 1

    monkeypatch.setenv("AGENTSTORE_INPUT", "ship it")
    module = _load_handler(handler)
    assert module.run("req-y") == ("SHIP IT", 1)


def test_running_quickstart_twice_keeps_user_edits(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    edited = ws.joinpath(*AGENT_DIR, "handler.py")
    edited.write_text("# 我自己改过的 handler\n", encoding="utf-8")

    _, out = _quickstart(tmp_path, monkeypatch)          # 第二次：必须跳过
    assert "skip" in out.lower()
    assert edited.read_text(encoding="utf-8") == "# 我自己改过的 handler\n"


# --------------------------------------------------------------------------
# 2. README 的流程：发布 → 安装 → 执行 → 重放 → 冲突 → 读回
# --------------------------------------------------------------------------
def test_replay_of_same_key_and_payload_returns_same_execution(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTSTORE_INPUT", raising=False)
    manifest, needs, rt, ledger = _installed(ws, str(tmp_path / "store.db"))
    handler = _load_handler(ws.joinpath(*AGENT_DIR, "handler.py")).run

    first = rt.execute("you", manifest.agent_id, handler, "demo-key-1", needs=needs)
    again = rt.execute("you", manifest.agent_id, handler, "demo-key-1", needs=needs)

    assert first.ok is True and first.duplicate is False
    assert again.duplicate is True
    assert again.id == first.id == "demo-key-1"
    assert again.output == first.output == EXPECTED
    assert again.charged_cents == first.charged_cents > 0
    # 重放不产生第二行用量 —— 幂等的意义就在这里
    rows = ledger.conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    assert rows == 1


def test_same_key_with_a_different_payload_is_a_conflict(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTSTORE_INPUT", raising=False)
    manifest, needs, rt, ledger = _installed(ws, str(tmp_path / "store.db"))
    handler = _load_handler(ws.joinpath(*AGENT_DIR, "handler.py")).run

    rt.execute("you", manifest.agent_id, handler, "demo-key-1", needs=needs)
    conflict = rt.execute("you", manifest.agent_id, handler, "demo-key-1",
                          needs=needs, tokens=999)

    assert conflict.ok is False
    assert conflict.error.startswith("idempotency_conflict"), conflict.error
    assert conflict.duplicate is False
    rows = ledger.conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    assert rows == 1, "冲突请求不该写用量"


def test_ledger_replay_reads_the_result_back(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTSTORE_INPUT", raising=False)
    manifest, needs, rt, ledger = _installed(ws, str(tmp_path / "store.db"))
    handler = _load_handler(ws.joinpath(*AGENT_DIR, "handler.py")).run
    first = rt.execute("you", manifest.agent_id, handler, "demo-key-1", needs=needs)

    rec = ledger.replay("you", "demo-key-1")
    assert rec is not None
    assert rec.duplicate is True
    assert rec.output == EXPECTED
    assert rec.cents == first.charged_cents
    assert ledger.replay("you", "never-used-key") is None


# --------------------------------------------------------------------------
# 3. agent.json 里声明的 needs 必须被摘要覆盖（否则「它要什么权限」可被改）
# --------------------------------------------------------------------------
def test_needs_is_covered_by_the_manifest_digest(tmp_path, monkeypatch):
    ws, _ = _quickstart(tmp_path, monkeypatch)
    base = load_manifest(ws.joinpath(*AGENT_DIR, "agent.json"))
    wider = dataclasses.replace(base, permissions=("fs.read", "fs.write"),
                               needs=("fs.write",))
    assert wider.digest() != base.digest()
