from openpyxl import load_workbook

from auditloop import cli
from auditloop.engine import AuditRun
from auditloop.models import EXISTENCE
from auditloop.workpaper import write_workpaper


def test_full_run_summary():
    run = cli.build_run()
    assert run.status == "attention_required"
    assert len(run.results) == 6
    assert all(r.status == "ok" for r in run.results)
    assert {f.ref for f in run.high} == {"INV-1003", "INV-1004", "G3/G6"}
    assert run.by_check()["revenue_cutoff"] == 2


def test_step_failure_does_not_abort_run():
    def boom():
        raise ValueError("CSV 有脏行")

    run = (AuditRun(entity="T", period_end=cli.fixtures.PERIOD_END)
           .register("bad_step", EXISTENCE, boom)
           .register("good_step", EXISTENCE, lambda: [])
           .run())
    assert run.status == "degraded"
    assert [r.status for r in run.results] == ["error", "ok"]
    bad = run.results[0]
    assert "ValueError" in bad.error
    assert bad.findings[0].ref == "ENGINE"
    assert run.results[1].status == "ok"


def test_workpaper_has_three_sheets(tmp_path):
    run = cli.build_run()
    p = write_workpaper(run, tmp_path / "wp.xlsx", detail={"总账分录": ["G1 ..."]})
    wb = load_workbook(p)
    assert wb.sheetnames == ["摘要", "例外", "明细"]
    ws = wb["例外"]
    assert ws.max_row == 1 + len(run.findings)
    assert wb["摘要"]["A1"].value.startswith("审计执行摘要")
    assert wb["明细"]["C2"].value == "G1 ..."


def test_markdown_contains_coverage_table():
    md = cli.build_run().to_markdown()
    assert "| 程序 | 认定 | 状态 | 例外 |" in md
    assert "revenue_cutoff" in md and "截止" in md
