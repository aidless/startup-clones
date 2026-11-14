"""`python3 -m auditloop.cli analytics` 的契约测试（打磨清单：分析性程序没接进 CLI）。

为什么这些断言长这样：

1. 走**子进程真跑**，不 import main()、不 mock —— 打磨项的原话是
   「`python3 -m auditloop.cli run` 只跑六项」，那么被修好的判据就必须是
   那条真实的命令行能跑出东西，而不是函数能返回东西。
2. 文本与 `--json` 的**信息一致性**用「用 JSON 字段逐字重建整行文本」来断言：
   只要两边任何一处数字、单位、年份、判定措辞不同，重建行就不在输出里。
   这比「两边都能看到 61.7」强得多，后者放得过四舍五入不一致。
3. 退出码是给脚本用的接口：0=跑完无异常、1=有异常、2=用法/输入错误。
   三条都要有，否则「有异常」这件事在 CI 里会变成不可见。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

AUDITLOOP_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ACME = FIXTURES / "acme_annual.json"
CLEAN = FIXTURES / "clean_annual.json"
SPARSE = FIXTURES / "revenue_only.json"

# 与 CLI 输出约定的精度：百分点与百分比 1 位、比率 2 位。
PRECISION = {"pp": 1, "%": 1, "x": 2}


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """真跑命令行。cwd 落在 audit-loop/ 下，等于 `cd audit-loop && python3 -m ...`。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(AUDITLOOP_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-m", "auditloop.cli", *args],
        cwd=str(cwd or AUDITLOOP_DIR), env=env, capture_output=True, text=True,
    )


def load_json_output(*args: str) -> dict:
    proc = run_cli(*args, "--json")
    assert proc.returncode in (0, 1), f"--json 跑失败：rc={proc.returncode}\n{proc.stderr}"
    return json.loads(proc.stdout)


def expected_line(item: dict) -> str:
    """只用 JSON 字段重建文本行 —— 这是「两种输出信息一致」的判据本身。"""
    p = PRECISION[item["unit"]]
    head = f"{item['label']}({item['unit']})"
    if item.get("ref"):
        head += f" FY{item['ref']}"
    if item["status"] == "insufficient":
        verdict, cur, prior, chg = "数据不足", "—", "—", "—"
    else:
        cur = f"{item['current']:.{p}f}"
        prior = "—" if item["prior"] is None else f"{item['prior']:.{p}f}"
        chg = "—" if item["change"] is None else f"{item['change']:+.{p}f}"
        verdict = f"异常({item['severity']})" if item["status"] == "flag" else "正常"
    line = f"{head} 本期 {cur} 上期 {prior} 变化 {chg} 判定 {verdict}"
    if item.get("detail"):
        line += f"  {item['detail']}"
    return line


# ---------------- 基本的「接进去了」 ----------------

def test_analytics_subcommand_runs_every_procedure():
    proc = run_cli("analytics", "--facts", str(ACME))
    assert proc.returncode == 1, proc.stderr
    out = proc.stdout
    assert "Acme Industrial" in out
    for label in ("应收增速差", "毛利率", "现金含量"):
        assert label in out, f"输出里没有 {label}，分析性程序没接进 CLI"


def test_known_numbers_come_from_the_fixture():
    """真实输入→输出：FY2026 应收增速 117.4% − 收入增速 5.0% = 112.4pt。"""
    data = load_json_output("analytics", "--facts", str(ACME))
    item = next(i for i in data["items"]
                if i["name"] == "revenue_vs_receivables" and i["ref"] == "2026")
    assert item["current"] == pytest.approx(112.4, abs=0.05)
    assert item["prior"] == pytest.approx(1.7, abs=0.05)
    assert item["flag"] is True and item["severity"] == "high"

    margin = next(i for i in data["items"] if i["name"] == "gross_margin" and i["ref"] == "2026")
    assert margin["current"] == pytest.approx(45.9, abs=0.05)

    cash = next(i for i in data["items"] if i["name"] == "cash_conversion" and i["ref"] == "2026")
    assert cash["current"] == pytest.approx(0.13, abs=0.005)


# ---------------- 两种输出信息一致 ----------------

def test_json_and_text_carry_the_same_items():
    data = load_json_output("analytics", "--facts", str(ACME))
    assert data["entity"] == "Acme Industrial"
    # 增速差需要相邻两年，FY2023 只能当基期（3 行）；毛利率与现金含量逐年有值（各 4 行）。
    counts = {name: sum(1 for i in data["items"] if i["name"] == name)
              for name in ("revenue_vs_receivables", "gross_margin", "cash_conversion")}
    assert counts == {"revenue_vs_receivables": 3, "gross_margin": 4, "cash_conversion": 4}

    text = run_cli("analytics", "--facts", str(ACME)).stdout.splitlines()
    for item in data["items"]:
        assert expected_line(item) in text, f"文本里找不到与 JSON 一致的行：{expected_line(item)}"

    # 反向：文本里不许出现 JSON 没有的指标行（多算也是不一致）
    body = [ln for ln in text
            if any(ln.startswith(i["label"]) for i in data["items"])]
    assert len(body) == len(data["items"])


def test_json_items_expose_the_required_fields():
    data = load_json_output("analytics", "--facts", str(ACME))
    for item in data["items"]:
        for key in ("name", "current", "prior", "change", "flag"):
            assert key in item, f"缺字段 {key}：{item}"
        assert isinstance(item["flag"], bool)
        assert (item["status"] == "flag") == item["flag"]


# ---------------- 退出码三条 ----------------

def test_exit_zero_when_no_anomaly():
    proc = run_cli("analytics", "--facts", str(CLEAN))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "异常" not in proc.stdout, "干净数据不该出现异常汇总行"


def test_exit_one_when_anomaly_found_and_summary_line_present():
    proc = run_cli("analytics", "--facts", str(ACME))
    assert proc.returncode == 1, "有异常项时退出码必须是 1，否则 CI 里看不见"
    data = json.loads(run_cli("analytics", "--facts", str(ACME), "--json").stdout)
    s = data["summary"]
    assert s["anomalies"] == 3
    assert f"异常 {s['anomalies']} 项 / 共 {s['total']} 项（未计算 {s['insufficient']} 项）" \
        in proc.stdout


def test_exit_two_on_missing_facts_file():
    proc = run_cli("analytics", "--facts", str(FIXTURES / "no_such_file.json"))
    assert proc.returncode == 2, "输入文件不存在是用法/输入错误，必须是 2"


def test_exit_two_on_broken_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert run_cli("analytics", "--facts", str(bad)).returncode == 2


def test_facts_is_required(tmp_path):
    assert run_cli("analytics").returncode == 2


# ---------------- 缺表要说话，不能静默 ----------------

def test_missing_series_is_reported_as_insufficient():
    """只有收入一列时，三条程序都算不出来 —— 必须显式写「数据不足」，
    否则与「跑了且没问题」在输出上完全一样（README 已知边界里点过这一条）。"""
    proc = run_cli("analytics", "--facts", str(SPARSE))
    assert proc.returncode == 0
    data = json.loads(run_cli("analytics", "--facts", str(SPARSE), "--json").stdout)
    assert len(data["items"]) == 3
    assert all(i["status"] == "insufficient" and i["flag"] is False for i in data["items"])
    assert proc.stdout.count("数据不足") == 3
