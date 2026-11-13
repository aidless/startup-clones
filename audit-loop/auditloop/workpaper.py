"""底稿输出：Excel（会计师真正会打开的东西）。

不做花哨报表 —— 三个 sheet 固定下来：摘要 / 例外 / 明细。
摘要给合伙人看，例外给现场做调整分录，明细给复核人抽查。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .engine import AuditRun
from .models import severity_rank

HEAD_FILL = PatternFill("solid", fgColor="1F2937")
HEAD_FONT = Font(color="FFFFFF", bold=True)
SEV_FILL = {"high": PatternFill("solid", fgColor="FDE2E1"),
            "medium": PatternFill("solid", fgColor="FEF3C7"),
            "low": PatternFill("solid", fgColor="E0F2FE")}


def _header(ws, row: int, values: list[str]) -> None:
    for i, v in enumerate(values, 1):
        c = ws.cell(row=row, column=i, value=v)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_workpaper(run: AuditRun, path: str | Path,
                    detail: dict[str, list[list]] | None = None) -> Path:
    wb = Workbook()

    ws = wb.active
    ws.title = "摘要"
    ws["A1"] = f"审计执行摘要 · {run.entity}"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = f"期末 {run.period_end} · 生成于 {date.today()} · 结论 {run.status}"
    _header(ws, 4, ["程序", "审计认定", "执行状态", "例外数", "high 例外", "错误"])
    row = 5
    for r in run.results:
        ws.cell(row=row, column=1, value=r.name)
        ws.cell(row=row, column=2, value=r.assertion)
        ws.cell(row=row, column=3, value=r.status)
        ws.cell(row=row, column=4, value=len(r.findings))
        ws.cell(row=row, column=5, value=r.high)
        ws.cell(row=row, column=6, value=r.error or "")
        if r.status == "error":
            for col in range(1, 7):
                ws.cell(row=row, column=col).fill = SEV_FILL["high"]
        row += 1
    _widths(ws, [26, 16, 14, 10, 12, 46])

    ws2 = wb.create_sheet("例外")
    _header(ws2, 1, ["程序", "认定", "严重度", "对象", "说明", "金额"])
    for i, f in enumerate(sorted(run.findings, key=lambda x: -severity_rank(x.severity)), 2):
        vals = [f.check, f.assertion, f.severity, f.ref, f.detail, f.amount]
        for j, v in enumerate(vals, 1):
            c = ws2.cell(row=i, column=j, value=v)
            c.alignment = Alignment(vertical="top", wrap_text=(j == 5))
        ws2.cell(row=i, column=3).fill = SEV_FILL.get(f.severity, SEV_FILL["low"])
    _widths(ws2, [22, 14, 10, 18, 62, 14])

    ws3 = wb.create_sheet("明细")
    _header(ws3, 1, ["数据集", "行号", "内容"])
    row_idx = 2
    if detail:
        for name, rows in detail.items():
            for idx, content in enumerate(rows, 1):
                ws3.cell(row=row_idx, column=1, value=name)
                ws3.cell(row=row_idx, column=2, value=idx)
                ws3.cell(row=row_idx, column=3, value=str(content))
                row_idx += 1
    # 失败程序的追踪进明细：摘要只放一句原因，完整栈放这里，复核时才有得看
    for res in run.results:
        if res.status == "error" and res.trace:
            ws3.cell(row=row_idx, column=1, value=f"失败追踪:{res.name}")
            ws3.cell(row=row_idx, column=2, value=0)
            cell = ws3.cell(row=row_idx, column=3, value=res.trace.strip())
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            row_idx += 1
    _widths(ws3, [18, 8, 90])

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(p)
    return p
