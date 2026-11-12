"""审计执行引擎：把检查编排成有状态的步骤序列。

两条纪律：
1. **单步失败不许拖垮整轮**。审计现场的数据永远有脏行，一步抛异常就终止，
   会计师会以为是软件坏了而不是数据有问题。所以捕获异常、记 status=error、继续。
2. **每一步必须声明它验证的审计认定**。底稿复核时，复核人先看「截止测试做了没」，
   而不是「跑了几个脚本」。
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from .models import Finding, StepResult


@dataclass
class Step:
    name: str
    assertion: str
    fn: Callable[[], list[Finding]]
    rows: Callable[[], int] | None = None


@dataclass
class AuditRun:
    entity: str
    period_end: date
    steps: list[Step] = field(default_factory=list)
    results: list[StepResult] = field(default_factory=list)

    def register(self, name: str, assertion: str, fn: Callable[[], list[Finding]],
                 rows: Callable[[], int] | None = None) -> "AuditRun":
        self.steps.append(Step(name, assertion, fn, rows))
        return self

    def run(self) -> "AuditRun":
        self.results = []
        for step in self.steps:
            r = StepResult(name=step.name, assertion=step.assertion)
            try:
                r.findings = list(step.fn() or [])
                r.rows_examined = step.rows() if step.rows else 0
            except Exception as exc:  # noqa: BLE001 —— 故意捕获全部，单步失败不终止整轮
                r.status = "error"
                r.error = f"{type(exc).__name__}: {exc}"
                r.findings = [Finding(
                    check=step.name, assertion=step.assertion, ref="ENGINE", severity="high",
                    detail=f"该程序执行失败，需人工补做：{r.error}")]
                r.trace = traceback.format_exc(limit=3)
            self.results.append(r)
        return self

    # ---- 汇总 ----
    @property
    def findings(self) -> list[Finding]:
        return [f for r in self.results for f in r.findings]

    @property
    def high(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "high"]

    @property
    def status(self) -> str:
        if any(r.status == "error" for r in self.results):
            return "degraded"
        if self.high:
            return "attention_required"
        return "clean"

    def by_check(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.check] = out.get(f.check, 0) + 1
        return out

    def coverage(self) -> list[tuple[str, str, str, int]]:
        """(程序, 认定, 状态, 例外数) —— 底稿第一页。"""
        return [(r.name, r.assertion, r.status, len(r.findings)) for r in self.results]

    def to_markdown(self) -> str:
        lines = [
            f"# 审计执行摘要 · {self.entity}",
            "",
            f"- 期末：{self.period_end}",
            f"- 结论：**{self.status}**（high 例外 {len(self.high)} 条）",
            "",
            "| 程序 | 认定 | 状态 | 例外 |",
            "| --- | --- | --- | ---: |",
        ]
        for name, assertion, status, n in self.coverage():
            lines.append(f"| {name} | {assertion} | {status} | {n} |")
        if self.findings:
            lines += ["", "## 例外清单", "", "| 程序 | 认定 | 严重度 | 对象 | 说明 |", "| --- | --- | --- | --- | --- |"]
            for f in sorted(self.findings, key=lambda x: (-{"high": 3, "medium": 2, "low": 1}[x.severity], x.check)):
                lines.append(f"| {f.check} | {f.assertion} | {f.severity} | {f.ref} | {f.detail} |")
        return "\n".join(lines)
