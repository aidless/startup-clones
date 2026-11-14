"""CLI 契约：六个内核的命令行必须长得一样（打磨清单第 1、2 条）。

第 1 条「CLI 风格不统一」和第 2 条「异常无共享基类」这两件事，本仓库的答案是
**不抽公共包，改用一份契约测试**：七个项目各自独立成仓库、彼此不 import，
抽公共包会让每个项目的「单独可用」变成「必须带另一个项目」。
于是把「统一」定义成可判定的四条，谁来写新 CLI 都照着过：

1. `--help` 退出 0，首行 `usage: <prog>`;
2. `--version` 退出 0，输出里带包版本（与 pyproject 的 version 一致）;
3. 有一个 `demo` 子命令（零配置可跑，这是七个项目的共同验收姿势）;
4. 未知子命令退出 2（argparse 的约定，脚本里能区分「用法错」与「跑失败」）。

第 2 条（异常基类）见 docs/POLISH.md：decision 是**不引入**跨项目异常基类，
每个项目自带 `<pkg>.errors` 或直接用内置异常，靠退出码契约对外。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# (目录, 模块, 包名)
PROJECTS = [
    ("audit-loop", "auditloop.cli", "auditloop"),
    ("geo-radar", "georadar.cli", "georadar"),
    ("cruxline", "cruxline.cli", "cruxline"),
    ("filing-lens", "filinglens.cli", "filinglens"),
    ("agent-inbox", "agentinbox.cli", "agentinbox"),
    ("agent-store", "agentstore.cli", "agentstore"),
]

IDS = [p[0] for p in PROJECTS]


def _cli(project: str, module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", module, *args],
                          cwd=ROOT / project, capture_output=True, text=True,
                          timeout=120)


def _pyproject_version(project: str) -> str:
    text = (ROOT / project / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, f"{project}/pyproject.toml 没有 version"
    return m.group(1)


@pytest.mark.parametrize("project,module,pkg", PROJECTS, ids=IDS)
def test_help_exits_zero_with_usage(project, module, pkg):
    r = _cli(project, module, "--help")
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.startswith("usage:"), r.stdout[:200]


@pytest.mark.parametrize("project,module,pkg", PROJECTS, ids=IDS)
def test_version_flag_matches_pyproject(project, module, pkg):
    r = _cli(project, module, "--version")
    assert r.returncode == 0, r.stderr[-500:]
    assert _pyproject_version(project) in r.stdout


@pytest.mark.parametrize("project,module,pkg", PROJECTS, ids=IDS)
def test_demo_subcommand_exists(project, module, pkg):
    r = _cli(project, module, "--help")
    assert "demo" in r.stdout


@pytest.mark.parametrize("project,module,pkg", PROJECTS, ids=IDS)
def test_unknown_subcommand_exits_two(project, module, pkg):
    """用法错必须是 2：脚本靠这个区分「我调错了」和「它跑失败了」。"""
    r = _cli(project, module, "definitely-not-a-subcommand")
    assert r.returncode == 2, (r.returncode, r.stderr[-300:])
