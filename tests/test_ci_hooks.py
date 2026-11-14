"""pre-push 钩子：解析器改了但基线没重记，推送必须被挡住。

判据两条（否则钩子是装饰）：
1. 矩阵与基线不一致 → 退出码非 0，且 stderr 里说清「怎么重记」；
2. 矩阵一致 → 退出码 0（不能只要推送就红，那样第二天就会被 `--no-verify` 绕过）。
用 `MATRIX_CMD` 这个真接缝喂替身命令，钩子本身按真 git 钩子的方式被 shell 调用。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "git-hooks" / "pre-push"


def test_hook_exists_and_is_executable():
    assert HOOK.exists(), HOOK
    assert HOOK.stat().st_mode & 0o111, "钩子不可执行，git 调用时会静默跳过"


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(HOOK)], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "MATRIX_CMD": cmd})


def test_hook_blocks_when_matrix_drifts():
    p = _run("exit 1")
    assert p.returncode != 0, p.stdout
    assert "matrix-record" in p.stdout + p.stderr, "没告诉人怎么重记基线"


def test_hook_passes_when_matrix_matches():
    p = _run("exit 0")
    assert p.returncode == 0, p.stdout + p.stderr
