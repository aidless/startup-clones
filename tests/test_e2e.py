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


@pytest.fixture(scope="module")
def chain():
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
