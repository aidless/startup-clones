"""Excel 进出：审计师手上是 Excel，这一层负责让它变成分析性程序能吃的 facts。

为什么这些断言长这样：

1. **roundtrip 用逐字相等**，不用 approx。模板是自己写出去的，读回来差一个
   浮点位就说明序列化路径有问题（比如写字符串、写小数位截断），
   这种偏差在 1e-6 容差下看不见，在客户账上就是一分钱的底稿差异。
2. **Excel → analytics 与 JSON → analytics 必须落在同一组数上**（容差 1e-6）。
   这一条是整张任务的核心：审计师换成 Excel 填数，结论不许跟着变。
3. **空单元格 = 缺失**，不是 0。写 0 会让三条程序算出「收入为零/毛利率为零」
   这种假结论，而缺失只会让那条程序报「数据不足」——后者是诚实的。
4. 坏年度带**行号**、坏表头**列出期望表头**：现场用户只会看报错文本，
   「第 4 行 年度 不是数字」比一句 ValueError 值钱得多。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

AUDITLOOP_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ACME_JSON = FIXTURES / "acme_annual.json"

SHEET = "年度数据"
HEADERS = ["年度", "营业收入", "应收账款", "毛利", "经营活动现金流"]


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """真跑命令行。

    工作区根目录名里带字面反斜杠（`F:\\deepseek`），把仓库路径塞进 PYTHONPATH
    会被冒号切成两段（`F` 与 `\\deepseek/...`），所以这里改用
    `-c` + `sys.path.insert` 起子进程 —— cwd 才能自由落在 tmp_path 上。
    """
    code = (
        "import sys, runpy;"
        f"sys.path.insert(0, {str(AUDITLOOP_DIR)!r});"
        f"sys.argv = ['auditloop', *{list(args)!r}];"
        "runpy.run_module('auditloop.cli', run_name='__main__')"
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd or AUDITLOOP_DIR), env=env, capture_output=True, text=True,
    )


def acme_years() -> dict:
    return json.loads(ACME_JSON.read_text(encoding="utf-8"))["years"]


def build_workbook(path: Path, rows: list[list], headers: list[str] | None = None) -> Path:
    """手搓一个最小工作簿：表头 + 可选注释行 + 数据行。"""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(headers if headers is not None else HEADERS)
    ws.append(["单位：元，可只填有数据的年份"])  # 模板第二行就是注释，数据从第 3 行起
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


# ---------------- 模板形状 ----------------

def test_template_has_expected_sheet_and_headers(tmp_path):
    from auditloop.excel import write_facts_template

    p = write_facts_template(tmp_path / "facts.xlsx")
    ws = load_workbook(p)[SHEET]
    assert [c.value for c in ws[1]][:5] == HEADERS
    assert isinstance(ws["A2"].value, str) and "单位" in ws["A2"].value
    assert "元" in ws["A2"].value


# ---------------- roundtrip：逐字相等 ----------------

def test_roundtrip_numbers_are_byte_identical(tmp_path):
    from auditloop.excel import read_facts, write_facts_template

    data = read_facts(write_facts_template(tmp_path / "facts.xlsx"))
    expected = acme_years()
    assert set(data["years"]) == set(expected), "年份集合必须原样读回"
    for year, row in expected.items():
        for field, value in row.items():
            assert data["years"][year][field] == value, (
                f"{year}.{field} 读回来不是原值：{data['years'][year][field]!r} != {value!r}"
            )


def test_read_facts_returns_entity_too(tmp_path):
    from auditloop.excel import read_facts, write_facts_template

    data = read_facts(write_facts_template(tmp_path / "facts.xlsx"))
    assert set(data) == {"entity", "years"}
    assert data["entity"] == "Acme Industrial"


# ---------------- Excel 与 JSON 喂出同一组数 ----------------

def test_excel_and_json_feed_analytics_the_same_numbers(tmp_path):
    from auditloop.analytics import assess, series_from_years
    from auditloop.excel import read_facts, write_facts_template

    from_excel = assess(series_from_years(
        read_facts(write_facts_template(tmp_path / "facts.xlsx"))["years"]))
    from_json = assess(series_from_years(acme_years()))

    assert len(from_excel) == len(from_json)
    for a, b in zip(from_excel, from_json):
        assert (a.name, a.ref, a.status, a.severity) == (b.name, b.ref, b.status, b.severity)
        for field in ("current", "prior", "change"):
            va, vb = getattr(a, field), getattr(b, field)
            if vb is None:
                assert va is None, f"{a.name} FY{a.ref}.{field} 应为 None，Excel 读成 {va!r}"
            else:
                assert va == pytest.approx(vb, abs=1e-6), (
                    f"{a.name} FY{a.ref}.{field}：Excel {va!r} != JSON {vb!r}"
                )


def test_excel_and_json_cli_agree(tmp_path):
    """整条命令行也走一遍：填 Excel 与填 JSON，--json 输出的每一项数值相同。"""
    from auditloop.excel import write_facts_template

    xlsx = write_facts_template(tmp_path / "facts.xlsx")
    p_x = run_cli("analytics", "--facts", str(xlsx), "--json")
    p_j = run_cli("analytics", "--facts", str(ACME_JSON), "--json")
    assert p_x.returncode == p_j.returncode == 1, p_x.stderr + p_j.stderr
    a, b = json.loads(p_x.stdout), json.loads(p_j.stdout)
    assert a["entity"] == b["entity"]
    assert len(a["items"]) == len(b["items"])
    for ia, ib in zip(a["items"], b["items"]):
        assert (ia["name"], ia["ref"], ia["status"]) == (ib["name"], ib["ref"], ib["status"])
        for field in ("current", "prior", "change"):
            if ib[field] is None:
                assert ia[field] is None
            else:
                assert ia[field] == pytest.approx(ib[field], abs=1e-6)


# ---------------- 空单元格：缺失，不是 0 ----------------

def test_blank_cell_is_missing_not_zero(tmp_path):
    from auditloop.excel import read_facts

    p = build_workbook(tmp_path / "gaps.xlsx", [
        [2023, 1000.0, None, None, 250.0],
        [2024, 1050.0, 108.0, 420.0, None],
    ])
    years = read_facts(p)["years"]
    assert years["2023"] == {"revenue": 1000.0, "cfo": 250.0}
    assert "receivables" not in years["2023"]
    assert "gross_profit" not in years["2023"]
    assert "cfo" not in years["2024"], "空单元格被读成 0 时这条会红"


def test_real_zero_stays_zero(tmp_path):
    from auditloop.excel import read_facts

    p = build_workbook(tmp_path / "zero.xlsx", [[2024, 0, 0.0, None, None]])
    row = read_facts(p)["years"]["2024"]
    assert row["revenue"] == 0
    assert row["receivables"] == 0.0


# ---------------- 报错要被人看懂 ----------------

def test_bad_year_raises_with_row_number(tmp_path):
    from auditloop.excel import read_facts

    p = build_workbook(tmp_path / "bad_year.xlsx", [
        [2023, 1000.0, 100.0, 400.0, 250.0],
        ["二〇二四", 1050.0, 108.0, 420.0, 210.0],
    ])
    with pytest.raises(ValueError) as exc:
        read_facts(p)
    msg = str(exc.value)
    assert "第 4 行" in msg, f"报错必须点名行号（数据从第 3 行起，坏的是第 4 行）：{msg}"
    assert "二〇二四" in msg


def test_bad_header_lists_expected_headers(tmp_path):
    from auditloop.excel import read_facts

    p = build_workbook(tmp_path / "bad_header.xlsx",
                       [[2023, 1000.0, 100.0, 400.0, 250.0]],
                       headers=["年度", "收入", "应收账款", "毛利", "经营活动现金流"])
    with pytest.raises(ValueError) as exc:
        read_facts(p)
    msg = str(exc.value)
    for h in HEADERS:
        assert h in msg, f"报错没列出期望表头 {h}：{msg}"


def test_missing_file_propagates(tmp_path):
    from auditloop.excel import read_facts

    with pytest.raises(FileNotFoundError):
        read_facts(tmp_path / "nope.xlsx")


def test_unsupported_suffix_is_a_value_error(tmp_path):
    from auditloop.excel import read_facts

    p = tmp_path / "facts.csv"
    p.write_text("年度,营业收入\n2023,1\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        read_facts(p)
    assert ".xlsx" in str(exc.value) and ".json" in str(exc.value)


def test_read_facts_accepts_json(tmp_path):
    from auditloop.excel import read_facts

    assert read_facts(ACME_JSON) == json.loads(ACME_JSON.read_text(encoding="utf-8"))


# ---------------- init → analytics 整条链 ----------------

def test_init_then_analytics_uses_the_generated_file(tmp_path):
    target = tmp_path / "al-init"
    proc = run_cli("init", "--dir", str(target))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    facts = target / "facts.xlsx"
    assert facts.is_file()
    assert "auditloop analytics --facts" in proc.stdout
    assert str(facts) in proc.stdout, "提示里必须带上真实路径，用户要能直接复制"

    out = run_cli("analytics", "--facts", str(facts))
    assert out.returncode == 1, out.stderr
    assert "Acme Industrial" in out.stdout
    for label in ("应收增速差", "毛利率", "现金含量"):
        assert label in out.stdout


def test_init_default_directory(tmp_path):
    """不带 --dir 时落在 out/init（README quickstart 用的就是这个路径）。"""
    proc = run_cli("init", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "out" / "init" / "facts.xlsx").is_file()
