"""第三轮审查（docs/REVIEW-R3-audit-crux.md）audit-loop 侧的复现测试。

覆盖 P0-1、P1-1、P1-2、P1-3、P1-7，以及 P2-1/P2-2 两条「文档与实现不符」的钉住。

共同的失效模式是同一条：**「没查」被写成「查了没问题」**。
- 单年数据没有可比上期，指标状态却是 `ok`；
- 三条指标全部算不出来，退出码仍是 0；
- 一个拼错的 `severity` 让「有 high 例外」与 `status=clean` 同时成立。

所以几乎每条都配一个**正对照**：修复后，原本正确的场景必须仍给原来的结论。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

AUDITLOOP_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ACME = FIXTURES / "acme_annual.json"
CLEAN = FIXTURES / "clean_annual.json"
SPARSE = FIXTURES / "revenue_only.json"

from auditloop import checks, cli, fixtures  # noqa: E402
from auditloop.analytics import Series, assess  # noqa: E402
from auditloop.engine import AuditRun  # noqa: E402
from auditloop.models import EXISTENCE, Entry, Finding  # noqa: E402


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """真起一个子进程跑 CLI。

    不用 `-m auditloop.cli` + PYTHONPATH：工作区根名里有字面反斜杠和冒号
    （`F:\deepseek`），冒号会被 PYTHONPATH 当分隔符切开，模块直接导入不到。
    改用 `-c` 显式把包目录塞进 sys.path。
    """
    code = ("import sys; sys.path.insert(0, {p!r});"
            "from auditloop.cli import main; sys.exit(main({a!r}))").format(
        p=str(AUDITLOOP_DIR), a=list(args))
    return subprocess.run([sys.executable, "-c", code],
                          cwd=str(cwd or AUDITLOOP_DIR), capture_output=True, text=True)


# ---------------- P0-1：没有可比基期 = 没判，不是「正常」 ----------------

def test_single_year_metrics_are_not_judged_ok():
    """单年数据：毛利率与现金含量都没有上期，判定必须是 insufficient。

    原实现 `status="flag" if f else "ok"` 对每个有值的年份一律先给 ok，
    于是「根本没做同比」被写成「正常」。
    """
    s = Series(revenue={2026: 1000.0}, receivables={2026: 300.0},
               gross_profit={2026: 400.0}, cfo={2026: 250.0})
    items = {i.name: i for i in assess(s)}
    assert items["gross_margin"].status == "insufficient"
    assert "无可比上期" in items["gross_margin"].detail
    assert items["cash_conversion"].status == "insufficient"
    assert "无可比上期" in items["cash_conversion"].detail


def test_first_year_of_multiyear_series_is_not_judged_ok():
    """多年度夹具的首年同样没有上期 —— 不是单年输入的怪癖。"""
    s = Series(revenue={2023: 1000.0, 2024: 1050.0},
               receivables={2023: 100.0, 2024: 108.0},
               gross_profit={2023: 400.0, 2024: 420.0},
               cfo={2023: 250.0, 2024: 210.0})
    items = {(i.name, i.ref): i for i in assess(s)}
    assert items[("gross_margin", "2023")].status == "insufficient"
    assert items[("cash_conversion", "2023")].status == "insufficient"
    # 正对照：有上期的那一年必须照旧判出「正常」
    assert items[("gross_margin", "2024")].status == "ok"
    assert items[("cash_conversion", "2024")].status == "ok"


def test_two_positive_years_still_report_normal():
    """正对照：两个正数年份、指标平稳 → 仍然判 ok，不许矫枉过正全变数据不足。"""
    s = Series(revenue={2024: 1000.0, 2025: 1100.0},
               receivables={2024: 100.0, 2025: 110.0},
               gross_profit={2024: 400.0, 2025: 440.0},
               cfo={2024: 250.0, 2025: 275.0})
    statuses = {(i.name, i.ref): i.status for i in assess(s)}
    assert statuses[("gross_margin", "2024")] == "insufficient"
    assert statuses[("gross_margin", "2025")] == "ok"
    assert statuses[("cash_conversion", "2025")] == "ok"
    assert statuses[("revenue_vs_receivables", "2025")] == "ok"


def test_single_year_cli_text_says_not_determined():
    """命令行文本也要说「数据不足」，不许印「判定 正常」。"""
    proc = run_cli("analytics", "--facts", str(FIXTURES / "single_year.json"))
    assert "毛利率(%) FY2026" in proc.stdout
    assert "判定 正常" not in proc.stdout
    assert proc.stdout.count("数据不足") == 3   # 毛利率 + 现金含量 + 应收增速差（一条都没算成）


# ---------------- P1-3：全部「数据不足」不许 exit 0 ----------------

def test_all_insufficient_exits_nonzero():
    """三条指标一条都没算成时，退出码必须区别于「跑完无异常」。
    契约（写进 README）：3 = 跑完，但一条指标都没判定成。"""
    proc = run_cli("analytics", "--facts", str(SPARSE))
    assert proc.returncode == 3, f"全 insufficient 仍是 {proc.returncode}：{proc.stdout}{proc.stderr}"
    assert proc.stderr.strip(), "说不清缺什么，运维无从修数据"


def test_clean_multiyear_still_exits_zero():
    # 正对照：三年干净数据（只有首年无可比上期）仍必须 exit 0
    proc = run_cli("analytics", "--facts", str(CLEAN))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_anomaly_still_exits_one():
    # 正对照：有异常仍是 1
    assert run_cli("analytics", "--facts", str(ACME)).returncode == 1


# ---------------- P1-1：demo 必崩（快速开始第一条命令） ----------------

def test_demo_runs_and_writes_workpaper(tmp_path):
    """README 把 demo 列为拿到包之后的第一条命令；它曾在打印分支上 AttributeError
    （`Namespace` 少了 `json`），跑完 6 个程序才崩，用户连「哪步坏了」都看不到。"""
    proc = run_cli("demo", cwd=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "AttributeError" not in proc.stderr
    wp = tmp_path / "out" / "workpaper.xlsx"
    assert wp.exists() and wp.stat().st_size > 0, "demo 没写出底稿"
    assert "审计执行摘要" in proc.stdout


# ---------------- P1-2：build_run 的前置计算在异常保护圈外 ----------------

def test_build_run_survives_dirty_row(monkeypatch):
    """原实现 `rec = checks.reconcile_bank(...)` 在 `register` 之前求值，
    脏行一进来整轮带 traceback 终止，`status=degraded` 这条防线根本没被触达。

    脏行照 README「按 dataclass 逐行构造」的接入路径造：ERP 导出里科目名为空。
    """
    good = fixtures.entries()
    bad = Entry(entry_id="GL-BAD", date=good[0].date, account=None,
                debit=1.0, memo="ERP 导出空科目名")
    monkeypatch.setattr(fixtures, "entries", lambda: [bad] + good)
    run = cli.build_run()                      # 不许抛
    assert run.status == "degraded"
    failed = [r for r in run.results if r.status == "error"]
    assert [r.name for r in failed] == ["bank_recon"]
    assert any(f.ref == "ENGINE" and f.severity == "high" for f in run.findings)
    # 其余程序照旧跑完（单步失败不终止整轮）
    assert len(run.results) == 6
    assert sum(1 for r in run.results if r.status == "ok") == 5


def test_build_run_clean_fixture_unchanged():
    # 正对照：干净夹具的结论与例外数不许变
    run = cli.build_run()
    assert run.status == "attention_required"
    assert len(run.high) == 3
    assert [r.name for r in run.results] == [
        "bank_recon", "ar_aging", "revenue_cutoff",
        "duplicate_payment", "ar_sanity", "ar_completeness"]
    assert not [r for r in run.results if r.status == "error"]


# ---------------- P1-7：severity 变体不许让 high 与 clean 并存 ----------------

def _run_with_severity(sev: str) -> AuditRun:
    run = AuditRun(entity="T", period_end=date(2026, 9, 30))
    run.register("step", EXISTENCE, lambda: [
        Finding(check="step", assertion=EXISTENCE, ref="X1", severity=sev, detail="测试"),
    ]).run()
    return run


@pytest.mark.parametrize("variant", ["HIGH", " high ", "High", "高"])
def test_high_variants_count_as_high(variant):
    run = _run_with_severity(variant)
    assert len(run.high) == 1, f"{variant!r} 没被当成 high"
    assert run.status == "attention_required"


def test_unknown_severity_never_yields_clean():
    """无法识别的严重度按 high 处理（fail-closed）：
    宁可多要一次人看一眼，也不许一个拼错的 severity 让结论落回 clean。"""
    run = _run_with_severity("critical")
    assert run.status != "clean"


def test_medium_only_run_is_still_clean():
    # 正对照：medium/low 例外仍可以与 clean 并存（README 已知边界明确写了）
    run = _run_with_severity("medium")
    assert run.status == "clean"
    assert run.high == []


def test_unknown_severity_text_is_preserved():
    # 正对照：归一化只改判定口径，不改底稿上印出来的原文
    assert "critical" in _run_with_severity("critical").to_markdown()


# ---------------- P2-1 / P2-2：文档与实现不符（只改文档） ----------------

README = (AUDITLOOP_DIR / "README.md").read_text(encoding="utf-8")


def test_boundary_section_has_no_drifting_line_refs():
    """已知边界段的用途是「指到实现位置」。行号会漂，改指函数/符号。"""
    boundary = README.split("## 已知边界", 1)[1]
    assert "checks.py:39" not in boundary and "checks.py:50" not in boundary
    assert "checks.py:115" not in boundary and "checks.py:122" not in boundary


def test_readme_demo_output_matches_real_run():
    """「演示输出（真实运行）」块必须能由真跑复现 —— 日期格式曾对不上
    （README 写 `09-20 与 09-21`，实测 `2026-09-20 与 2026-09-21`）。"""
    run = cli.build_run()
    real = [f.detail for f in run.findings if f.check == "duplicate_payment"]
    assert real, "夹具里应当有重复付款例外"
    assert real[0] in README, f"README 的演示块与实测不符：{real[0]}"


def test_readme_documents_exit_codes_including_three():
    """退出码契约必须写在 README 里：3 = 跑完但一条指标都没判定成。"""
    assert "退出码" in README or "exit" in README
    assert "3" in README.split("退出码", 1)[1][:400] if "退出码" in README else True
    assert "一条都没判定成" in README or "未判定" in README


def test_readme_documents_unknown_severity_contract():
    assert "unknown" in README.lower() or "无法识别" in README
