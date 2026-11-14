#!/usr/bin/env python3
"""打磨验收闸：八个项目逐项打分，红的就是没打磨好。

为什么要有这个脚本：'打磨' 听起来像审美，实际上是一组可判定的东西 ——
README 里有没有能让陌生人跑起来的命令、边界有没有写、CLI 的 --help 会不会崩、
库里还有没有 print 调试残留、TODO 有没有在涨。这些都能机器判。

判据分两类：
- **硬项**（readme / pyproject / cli / limits / hygiene）：不过就是没打磨好，脚本 exit 1。
- **软项**（数字 / 结构 / 测试数）：只报数，不阻断 —— 它们取决于项目性质。

用法：
    python3 scripts/polish_audit.py                 # 只看硬项
    python3 scripts/polish_audit.py --tests         # 顺带跑 pytest（慢，约 1 分钟）
    python3 scripts/polish_audit.py --project geo-radar
    python3 scripts/polish_audit.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"docs", "scripts", "go-to-market"}  # go-to-market 是文档包，单独判
# 跑过测试/demo 之后仓库里会长出这些**生成物**目录，它们不是项目：
# `.pytest_cache` 曾被当成一个项目判红三次（没有 README/pyproject/边界段），
# 与「项目没打磨好」在输出上长得一模一样 —— 必须按名字排除，而不是靠有没有 README。
GENERATED = {".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__",
             "out", "reports", "node_modules", ".git", ".venv", "venv",
             "artifacts", "dist", "build"}
PKG = {  # 目录 → 包名（CLI 探测用）
    "agent-inbox": "agentinbox",
    "agent-store": "agentstore",
    "audit-loop": "auditloop",
    "cruxline": "cruxline",
    "filing-lens": "filinglens",
    "geo-radar": "georadar",
    "console": None,
}

HEADING = re.compile(r"^#{2,3}\s+(.+)$", re.M)
CODE_BLOCK = re.compile(r"```[a-z]*\n(.+?)```", re.S)
NUMBERED_FACT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|份|家|条|个|次|秒|分钟|ms|s\b|行|万|B\b|万条)")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def check_readme(d: Path) -> tuple[bool, str]:
    txt = read(d / "README.md")
    if not txt:
        return False, "没有 README.md"
    heads = [h.strip() for h in HEADING.findall(txt)]
    has_quick = any(re.search(r"快速|quick ?start|用法|usage|开始", h, re.I) for h in heads)
    has_cmd = bool(CODE_BLOCK.search(txt))
    if not has_quick:
        return False, f"{len(heads)} 个二级标题但没有「快速开始/用法」段"
    if not has_cmd:
        return False, "有用法段但没有可复制的代码块"
    return True, f"{len(heads)} 段 / {len(txt)} 字 / 有命令块"


def check_limits(d: Path) -> tuple[bool, str]:
    """README 必须自己写出边界。没有边界的 README 等于广告。"""
    txt = read(d / "README.md")
    if not txt:
        return False, "无 README"
    # 关键词允许出现在标题任意位置：「已知局限」「边界与不做的事」都算
    m = re.search(r"^#{2,3}\s*.*(已知边界|边界与|边界|局限|限制|不做|Limitations?|Known issues).*$",
                  txt, re.M | re.I)
    if not m:
        return False, "没有「已知边界/局限」段"
    start = m.end()
    nxt = HEADING.search(txt, start)
    body = txt[start: nxt.start() if nxt else len(txt)].strip()
    if len(body) < 40:
        return False, "边界段几乎是空的"
    return True, f"边界段 {len(body)} 字"


def check_pyproject(d: Path) -> tuple[bool, str]:
    p = d / "pyproject.toml"
    if not p.exists():
        return False, "没有 pyproject.toml"
    txt = read(p)
    miss = [k for k in ("name", "version") if not re.search(rf"^{k}\s*=", txt, re.M)]
    if miss:
        return False, f"pyproject 缺 {miss}"
    has_path = 'pythonpath' in txt or 'packages' in txt
    return True, "name/version 齐全" + ("" if has_path else "（无 pythonpath，注意导入）")


def check_cli(d: Path) -> tuple[bool, str]:
    pkg = PKG.get(d.name)
    if not pkg:
        return True, "无 CLI（跳过）"
    cp = subprocess.run([sys.executable, "-m", f"{pkg}.cli", "--help"],
                        cwd=d, capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        first = (cp.stderr or cp.stdout).strip().splitlines()[:1]
        return False, f"--help 退出 {cp.returncode}：{first}"
    if "usage" not in cp.stdout.lower():
        return False, "--help 没有输出 usage"
    return True, f"{len(cp.stdout.splitlines())} 行帮助"


def check_hygiene(d: Path) -> tuple[bool, str]:
    """库里不许留调试痕迹。这些不影响功能，但会让读代码的人不敢信这个仓库。"""
    srcs = [p for p in d.rglob("*.py")
            if ".git" not in p.parts and "tests" not in p.parts and "scripts" not in p.parts]
    todos, bare, prints = [], [], []
    for p in srcs:
        for i, line in enumerate(read(p).splitlines(), 1):
            if re.search(r"\b(TODO|FIXME|XXX)\b", line):
                todos.append(f"{p.relative_to(d)}:{i}")
            if re.search(r"except\s*(Exception)?\s*:\s*(#.*)?$", line):
                bare.append(f"{p.relative_to(d)}:{i}")
            if re.search(r"^\s*print\(", line) and "cli" not in p.name:
                prints.append(f"{p.relative_to(d)}:{i}")
    bad = []
    if todos:
        bad.append(f"TODO×{len(todos)}（{todos[0]}）")
    if bare:
        bad.append(f"裸 except×{len(bare)}（{bare[0]}）")
    if len(prints) > 2:
        bad.append(f"print×{len(prints)}（{prints[0]}）")
    if bad:
        return False, "；".join(bad)
    return True, f"{len(srcs)} 个源文件干净"


def check_numbers(d: Path) -> tuple[bool, str]:
    """软项：README 里有没有具体数字。有数字的 README 才像跑过。"""
    txt = read(d / "README.md")
    hits = NUMBERED_FACT.findall(txt)
    return bool(hits), f"{len(hits)} 处带单位数字"


def check_tests(d: Path, run: bool) -> tuple[bool, str]:
    files = [p for p in (d / "tests").glob("test_*.py")] if (d / "tests").exists() else []
    if not files:
        return False, "没有 tests/test_*.py"
    if not run:
        return True, f"{len(files)} 个测试文件（未跑）"
    cp = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=d,
                        capture_output=True, text=True, timeout=900)
    tail = [l for l in cp.stdout.strip().splitlines() if "passed" in l or "failed" in l]
    if cp.returncode != 0:
        return False, (tail[-1] if tail else "pytest 失败")
    return True, (tail[-1] if tail else "pytest ok")


CHECKS = [
    ("readme", check_readme, True),
    ("limits", check_limits, True),
    ("pyproject", check_pyproject, True),
    ("cli", check_cli, True),
    ("hygiene", check_hygiene, True),
    ("numbers", check_numbers, False),
]


def audit(d: Path, run_tests: bool) -> dict:
    res = {"project": d.name, "checks": {}}
    for name, fn, hard in CHECKS:
        try:
            ok, note = fn(d)
        except Exception as exc:  # noqa: BLE001 —— 单项崩不能拖垮整张表
            ok, note = False, f"检查器异常：{exc}"
        res["checks"][name] = {"ok": ok, "hard": hard, "note": note}
    ok, note = check_tests(d, run_tests)
    res["checks"]["tests"] = {"ok": ok, "hard": False, "note": note}
    res["hard_fail"] = [k for k, v in res["checks"].items() if v["hard"] and not v["ok"]]
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests", action="store_true", help="顺带跑 pytest")
    ap.add_argument("--project", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dirs = ([ROOT / args.project] if args.project else
            [p for p in sorted(ROOT.iterdir())
             if p.is_dir()
             and p.name not in SKIP
             and p.name not in GENERATED
             and not p.name.startswith(".")
             and (p / "README.md").exists()])
    table = [audit(d, args.tests) for d in dirs]

    if args.json:
        print(json.dumps(table, ensure_ascii=False, indent=2))
    else:
        names = [n for n, _, _ in CHECKS] + ["tests"]
        w = max(len(n) for n in names) + 1
        print(f"{'项目':<14}" + "".join(f"{n:<{w}}" for n in names))
        for r in table:
            row = f"{r['project']:<14}"
            for n in names:
                c = r["checks"][n]
                row += f"{('✓' if c['ok'] else ('✗' if c['hard'] else '·')):<{w}}"
            print(row)
        print()
        for r in table:
            if r["hard_fail"]:
                print(f"[{r['project']}]")
                for k in r["hard_fail"]:
                    print(f"  ✗ {k}: {r['checks'][k]['note']}")

    bad = [r for r in table if r["hard_fail"]]
    if bad:
        print(f"\n{len(bad)}/{len(table)} 个项目有硬项未过。")
        return 1
    print(f"\n{len(table)} 个项目硬项全过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
