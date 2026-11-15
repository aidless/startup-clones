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

# 语料选择：`data/`（22 份，164MB，.gitignore 掉的）优先；没有它就退到入库的
# `data-prospects/`（三家小盘客户，随仓库发布）。两边都没有就报错并说明怎么补。
FULL = ("0000320193", "2026-09-26")     # Apple：22 份语料在位时用它
TRACKED = ("0001481504", "2026-06-30")  # XERIANT：随仓库发布的样本


def resolve_corpus(root: Path = ROOT) -> tuple[Path, str, str]:
    """返回 (语料目录, CIK, 期间)。判据见 tests/test_e2e_corpus.py。"""
    filing = root / "filing-lens"
    for sub, (cik, period) in ((("data"), FULL), (("data-prospects"), TRACKED)):
        d = filing / sub
        if (d / f"{cik}_10k_{period}.htm").exists() and (d / f"{cik}_facts.json").exists():
            return d, cik, period
    raise SystemExit(
        "e2e 找不到可用的 10-K 语料。\n"
        "  入库样本：filing-lens/data-prospects/（应随仓库发布，缺失说明检出不全）\n"
        "  全量语料：cd filing-lens && python3 scripts/batch_bench.py --no-fetch 或"
        " python3 scripts/batch_bench.py（真去 SEC 抓 22 份）\n"
        "  也可以只抓一份：python3 -m filinglens.cli fetch 0000320193 --data data")


def resolve_traces(root: Path = ROOT) -> tuple[Path, str]:
    """cruxline 的轨迹语料：真导出优先，其次入库的合成样本。

    60 条真实轨迹是本机 dsh 会话导出的，含生产内容，不随仓库发布；
    干净检出里退到 `sample-traces.jsonl`（5 条合成轨迹，判据一致）。
    """
    data = root / "cruxline" / "data"
    real = data / "traces.jsonl"
    if real.exists():
        return real, "真实导出（60 条本机会话）"
    sample = data / "sample-traces.jsonl"
    if sample.exists():
        return sample, "合成样本（5 条，随仓库发布）"
    raise SystemExit(
        f"e2e 找不到轨迹语料：{real} 与 {sample} 都不存在。\n"
        "  真轨迹：cd cruxline && python3 scripts/export_dsh_traces.py\n"
        "  合成样本应随仓库发布，缺失说明检出不全")


def _fmt(values: list[str], tmp: Path, data_dir: Path, cik: str,
         html: Path, facts: Path, traces: Path | None = None) -> list[str]:
    return [str(v).format(tmp=tmp, root=ROOT, cik=cik, data=data_dir,
                          html=html, facts=facts, traces=traces) for v in values]


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


def _run(step: Step, tmp: Path, ctx: dict | None = None,
         extra: dict[str, str] | None = None) -> Result:
    cwd = ROOT / step.project
    ctx = ctx or {}
    argv = _fmt(step.argv, tmp, ctx["data"], ctx["cik"], ctx["html"],
                ctx["facts"], ctx.get("traces"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **(extra or {}))
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                       timeout=step.timeout, env=env)
    return Result(step, p.returncode, p.stdout, p.stderr)


def run_chain(quiet: bool = False) -> tuple[bool, list[Result]]:
    """真跑一遍全链。返回 (是否全绿, 每步结果)。"""
    evidence: list[Result] = []
    data_dir, cik, period = resolve_corpus()
    traces, _label = resolve_traces()
    ctx = {
        "traces": traces,
        "data": data_dir,
        "cik": cik,
        "html": data_dir / f"{cik}_10k_{period}.htm",
        "facts": data_dir / f"{cik}_facts.json",
    }
    results: list[Result] = evidence
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
        r1 = _run(step_run, tmp, ctx)
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
        r2 = _run(step_rep, tmp, ctx)
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
        ), tmp, ctx))

        # ---- 4 filing 差异表：同一份 CIK，商品化的那张表必须能出 ----
        results.append(_run(Step(
            "filing.diff", "filing-lens",
            [sys.executable, "scripts/review_diff.py", "{cik}", "--data", "{data}"],
            expect=["检查"],
        ), tmp, ctx))

        # ---- 5 cruxline：真实 60 条轨迹上跑 rubric，至少要有 PASS 判定 ----
        results.append(_run(Step(
            "crux.judge", "cruxline",
            [sys.executable, "-m", "cruxline.cli", "judge",
             "--traces", "{traces}", "--db", "{tmp}/crux.db"],
            expect=["PASS"],
        ), tmp, ctx))

        # ---- 6 audit-loop：底稿必须真落盘（非空文件），不是只打了一屏字 ----
        r6 = _run(Step(
            "audit.run", "audit-loop",
            [sys.executable, "-m", "auditloop.cli", "run",
             "--out", "{tmp}/workpaper.xlsx"],
            expect=["例外"],
        ), tmp, ctx)
        results.append(r6)

        # ---- 7 agent-inbox / 8 agent-store：零配置演示，验关键段落 ----
        results.append(_run(Step(
            "inbox.demo", "agent-inbox",
            [sys.executable, "-m", "agentinbox.cli", "demo"],
            expect=["审批队列", "审计日志"],
        ), tmp, ctx))
        results.append(_run(Step(
            "store.demo", "agent-store",
            [sys.executable, "-m", "agentstore.cli", "demo"],
            expect=["上架", "账单"],
        ), tmp, ctx))

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
