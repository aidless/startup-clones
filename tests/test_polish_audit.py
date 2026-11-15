"""打磨判据自身的守卫：`polish_audit.check_hygiene` 必须能红，也不能对模板文案误报。

这两条都是踩出来的：
- 真实调试 `print(` 留在库里 → 必须判红（否则这条判据是装饰）；
- 生成器里**内嵌的模板字符串**里写 `print(...)`（`agentstore/quickstart.py:118-144`
  的 `RUN_PY` 就是给用户看的脚本正文）→ 不许判红。原来按行正则数，一段模板正文
  能把「print×8」扣到项目头上，而那段代码根本不是本模块的调试输出。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import polish_audit  # noqa: E402


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    proj = tmp_path / "demo"
    (proj / "demo").mkdir(parents=True)
    (proj / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")
    for rel, text in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return proj


def test_real_debug_prints_are_flagged(tmp_path):
    proj = _project(tmp_path, {"demo/core.py": (
        "def f():\n"
        "    print('1')\n"
        "    print('2')\n"
        "    print('3')\n"
        "    return 1\n"
    )})
    ok, note = polish_audit.check_hygiene(proj)
    assert ok is False, note
    assert "print×3" in note, note


def test_prints_inside_a_template_string_are_not_flagged(tmp_path):
    proj = _project(tmp_path, {"demo/gen.py": (
        "TEMPLATE = '''\n"
        "print('a')\n"
        "print('b')\n"
        "print('c')\n"
        "print('d')\n"
        "'''\n"
        "\n"
        "def build():\n"
        "    return TEMPLATE\n"
    )})
    ok, note = polish_audit.check_hygiene(proj)
    assert ok is True, note


def test_template_and_real_prints_are_told_apart(tmp_path):
    proj = _project(tmp_path, {"demo/gen.py": (
        "TEMPLATE = '''\n"
        "print('a')\n"
        "print('b')\n"
        "'''\n"
        "\n"
        "def build():\n"
        "    print('真的调试输出')\n"
        "    return TEMPLATE\n"
    )})
    ok, note = polish_audit.check_hygiene(proj)
    assert ok is True, note   # 一条真 print 在阈值内，模板里的不算
    proj2 = _project(tmp_path / "second", {"demo/gen.py": (
        "TEMPLATE = '''\nprint('a')\nprint('b')\n'''\n"
        "def build():\n    print(1)\n    print(2)\n    print(3)\n    return TEMPLATE\n"
    )})
    ok2, note2 = polish_audit.check_hygiene(proj2)
    assert ok2 is False, note2
    assert "print×3" in note2, note2


def test_broken_syntax_does_not_make_the_gate_crash(tmp_path):
    """解析不了的文件不许让整个判据抛异常——宁可判红，也不许静默放行。"""
    proj = _project(tmp_path, {"demo/broken.py": "def f(:\n    pass\n"})
    ok, note = polish_audit.check_hygiene(proj)
    assert ok is False, note
    assert "语法" in note, note
