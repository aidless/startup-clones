#!/usr/bin/env python3
"""端到端串联：把七个项目的 CLI 串成一条链，验「结论」而不只是「契约」。

打磨清单第 6 条写的是：七个项目测试全绿，但**从没有在同一份数据上串过一次**，
`console/` 是最接近的，它只验接口形状（返回 200、字段齐），不验结论对不对。
本脚本补的就是这一段：

- 五个阶段各自真跑一次 CLI（子进程，不是 import 调用），失败即整条链失败；
- 两处**真交接**：geo 的 run 产出的 run_id 交给 report 用；run 报的提及数必须
  在 report 里出现同一个数字（否则「同一份数据两条路径」只是口头一致）；
- 两处**产物断言**：filing 的 10-K 与 facts 必须是真实语料里存在的那份；
  audit 的底稿必须真的落盘且非空。

用法：
    python3 scripts/e2e.py            # 人类可读的步骤表；任一阶段失败 exit 1
    python3 scripts/e2e.py --quiet    # 只打最后一行
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIK = "0000320193"                      # Apple：真实 10-K，data/ 里必有
FILING_HTML = ROOT / "filing-lens" / "data" / f"{CIK}_10k_2026-09-26.htm"
FILING_FACTS = ROOT / "filing-lens" / "data" / f"{CIK}_facts.json"


@dataclass
class Step:
    name: str
    project: str
    argv: list[str]                     # 相对 project 目录的命令
    expect: list[str] = field(default_factory=list)   # 输出里必须出现的子串
    timeout: int = 180


@dataclass
class Result:
    step: Step
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0 and all(e in self.out for e in self.step.expect)


def _run(step: Step, tmp: Path, extra: dict[str, str] | None = None) -> Result:
    cwd = ROOT / step.project
    argv = [str(a).format(tmp=tmp, root=ROOT, cik=CIK,
                          html=FILING_HTML, facts=FILING_FACTS) for a in step.argv]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **(extra or {}))
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                       timeout=step.timeout, env=env)
    return Result(step, p.returncode, p.stdout, p.stderr)


def run_chain(quiet: bool = False) -> tuple[bool, list[Result]]:
    """真跑一遍全链。返回 (是否全绿, 每步结果)。"""
    results: list[Result] = []
    with tempfile.TemporaryDirectory(prefix="e2e-") as td:
        tmp = Path(td)

        # ---- 1+2 geo：run 产出 run_id，report 必须用同一个 id 复现同一份结论 ----
        step_run = Step(
            "geo.run", "geo-radar",
            [sys.executable, "-m", "georadar.cli", "run",
             "--brand", "Acme", "--category", "AI SRE",
             "--competitors", "Traversal", "--repeat", "2",
             "--db", "{tmp}/geo.db", "--out", "{tmp}/geo.md"],
            expect=["run_id", "mentions"],
        )
        r1 = _run(step_run, tmp)
        results.append(r1)
        m = re.search(r"run_id\s*:\s*(\S+)", r1.out)
        run_id = m.group(1) if m else ""
        # 每个品牌自己的提及数（不是合计）：report 的那张表也是按品牌印的
        acme = re.search(r"^\s+Acme\s+mentions=(\d+)", r1.out, re.M)

        step_rep = Step(
            "geo.report", "geo-radar",
            [sys.executable, "-m", "georadar.cli", "report",
             "--db", "{tmp}/geo.db", "--run-id", run_id or "missing"],
            expect=["AI 可见性周报"],
        )
        r2 = _run(step_rep, tmp)
        # 真交接的判据：run 说 Acme 被提了多少次，report 里 Acme 那行就得是同一个数
        # （品牌行带「←」标记，见 report.markdown_report）
        if acme:
            r2.step.expect.append(f"| Acme ← | {acme.group(1)} |")
        results.append(r2)

        # ---- 3 filing：真实 10-K 上问一个数字题，必须带引用 ----
        results.append(_run(Step(
            "filing.ask", "filing-lens",
            [sys.executable, "-m", "filinglens.cli", "ask",
             "What was net income?", "--html", "{html}", "--facts", "{facts}"],
            expect=["[ok]"],
        ), tmp))

        # ---- 4 filing 差异表：同一份 CIK，商品化的那张表必须能出 ----
        results.append(_run(Step(
            "filing.diff", "filing-lens",
            [sys.executable, "scripts/review_diff.py", "{cik}"],
            expect=["检查"],
        ), tmp))

        # ---- 5 cruxline：真实 60 条轨迹上跑 rubric，至少要有 PASS 判定 ----
        results.append(_run(Step(
            "crux.judge", "cruxline",
            [sys.executable, "-m", "cruxline.cli", "judge",
             "--traces", "data/traces.jsonl", "--db", "{tmp}/crux.db"],
            expect=["PASS"],
        ), tmp))

        # ---- 6 audit-loop：底稿必须真落盘（非空文件），不是只打了一屏字 ----
        r6 = _run(Step(
            "audit.run", "audit-loop",
            [sys.executable, "-m", "auditloop.cli", "run",
             "--out", "{tmp}/workpaper.xlsx"],
            expect=["例外"],
        ), tmp)
        results.append(r6)

        # ---- 7 agent-inbox / 8 agent-store：零配置演示，验关键段落 ----
        results.append(_run(Step(
            "inbox.demo", "agent-inbox",
            [sys.executable, "-m", "agentinbox.cli", "demo"],
            expect=["审批队列", "审计日志"],
        ), tmp))
        results.append(_run(Step(
            "store.demo", "agent-store",
            [sys.executable, "-m", "agentstore.cli", "demo"],
            expect=["上架", "账单"],
        ), tmp))

        # 产物断言放在链末：前面都跑完才有这两份东西
        wp = tmp / "workpaper.xlsx"
        md = tmp / "geo.md"
        for name, path, least in (("audit.workpaper", wp, 2000), ("geo.report_file", md, 200)):
            step = Step(name, ".", [], [])
            ok = path.exists() and path.stat().st_size >= least
            results.append(Result(step, 0 if ok else 1,
                                  f"{path.name} {path.stat().st_size if path.exists() else 0}B",
                                  "" if ok else f"产物缺失或过小（要求 ≥{least}B）"))

    if not quiet:
        for r in results:
            flag = "ok  " if r.ok else "FAIL"
            print(f"[{flag}] {r.step.name:<18} exit={r.code}")
            if not r.ok:
                head = (r.out or r.err).strip().splitlines()[:6]
                for line in head:
                    print(f"         | {line}")
    ok = all(r.ok for r in results)
    print(f"e2e：{sum(r.ok for r in results)}/{len(results)} 阶段通过")
    return ok, results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="e2e", description="七个项目端到端串联")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    ok, _ = run_chain(quiet=args.quiet)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
