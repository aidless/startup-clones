"""端到端串联的测试：链必须真跑通，且删掉任何一段都要被抓到。

为什么值得一个测试：`console/` 只验接口契约（字段齐、200），不验结论；
这条链验的是「同一份数据走两个入口必须给同一个数字」和「产物真的落盘」。
它第一次跑就抓到一个真缺陷 —— `cruxline judge --traces data/traces.jsonl`
把整份文件当 JSON 读，`JSONDecodeError: Extra data: line 2`（见
`cruxline/tests/test_cli_traces.py`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from e2e import run_chain  # noqa: E402

EXPECTED_STEPS = [
    "geo.run", "geo.report",
    "filing.ask", "filing.diff",
    "crux.judge", "audit.run",
    "inbox.demo", "store.demo",
    "audit.workpaper", "geo.report_file",
]
EXPECTED_PROJECTS = {"geo-radar", "filing-lens", "cruxline", "audit-loop",
                     "agent-inbox", "agent-store"}


FILING = ROOT / "filing-lens"
PROSPECTS = FILING / "data-prospects"                 # 入库：三家小盘客户的 10-K
TRACES = ROOT / "cruxline" / "data" / "traces.jsonl"  # 不入库：60 条真实 agent 轨迹


def _missing_corpora() -> list[str]:
    """这条链还缺什么语料。缺了就把「缺什么 + 怎么补」写进 skip reason。

    分三层看：
    - `filing.ask` / `filing.diff` 已经有 `scripts/e2e.py:resolve_corpus()` 兜底，
      没有 `data/` 时退到**入库的** `data-prospects/`（XERIANT 0001481504），
      所以这两段在干净检出里照样真跑；
    - `crux.judge` 读 `cruxline/data/traces.jsonl`（60 条真实 agent 会话），
      它来自本机 dsh 会话日志、**无法**随仓库发布，也没有公网来源；
    - `data-prospects/` 是入库的，缺了说明检出不全（不是「没抓语料」）。
    """
    missing = []
    if not PROSPECTS.is_dir():
        missing.append(f"入库样本缺失：{PROSPECTS}（不应该发生，说明检出不全）")
    if not TRACES.exists():
        missing.append(
            f"缺少 {TRACES}；这批轨迹是 60 条真实 agent 会话（`~/.dsh/sessions` 导出，"
            "含生产内容，不随仓库发布）：`cd cruxline && python3 scripts/export_dsh_traces.py`")
    return missing


@pytest.fixture(scope="module")
def chain():
    missing = _missing_corpora()
    if missing:
        pytest.skip("十阶段链路跑不了，" + "；".join(missing))
    ok, results = run_chain(quiet=True)
    return ok, results


def test_chain_is_green(chain):
    ok, results = chain
    failed = [f"{r.step.name}(exit={r.code})" for r in results if not r.ok]
    assert ok, f"失败阶段：{failed}"


def test_chain_covers_every_core_project(chain):
    _, results = chain
    assert {r.step.project for r in results} >= EXPECTED_PROJECTS


def test_chain_has_no_silently_dropped_stage(chain):
    """按名字逐条对齐：少了一段或改了名，这条会红（不是只数个数）。"""
    _, results = chain
    assert [r.step.name for r in results] == EXPECTED_STEPS
