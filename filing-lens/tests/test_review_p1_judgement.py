"""审查报告 P1（filing-lens 判定面）三条的复现测试（2026-11-12 审查）。

1. 概念覆盖率被通用词刷满：`full-time` 被分词成 full / time，任何含 "time" 的段落
   都算「覆盖了员工这个概念」→ 419 个 chunk 里 39 个拿 1.0，Item 1¶35 通篇无员工词。
2. `RESPECTIVELY_RE` 把年份当人数：TI 的「As of December 31, 2025 and 2024, as a result
   of employees' elections…」→ 人数答成 2025。
3. `facts.sql_query` 没有只读约束：`DROP TABLE facts` 能执行成功。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from filinglens import facts
from filinglens.answer import headcount_number
from filinglens.index import BM25Index, Hit, coverage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# `data/` 是被 .gitignore 掉的 164MB SEC 语料，干净检出里没有它；补齐命令写进 reason。
_HOW_TO_FETCH = ("先跑 `cd filing-lens && python3 scripts/batch_bench.py` 抓回 22 份 10-K"
                 "（只用本地已有文件：python3 scripts/batch_bench.py --no-fetch）")


def _has(cik: str) -> bool:
    return ((DATA / f"{cik}_facts.json").exists()
            and bool(list(DATA.glob(f"{cik}_10k_*.htm"))))


# ---------------- P1-1 概念覆盖率不许被通用词刷满 ----------------

def _hit(text: str) -> Hit:
    from filinglens import edgar
    chunks, _, _ = edgar.parse(f"<html><body><p>{text}</p></body></html>", doc="t")
    return Hit(chunk=chunks[0], score=1.0, matched=[])


def test_generic_token_does_not_cover_headcount_concept():
    """段落里只有 "time"（来自 "from time to time"）—— 不能算讲到员工。"""
    hit = _hit("We may from time to time repurchase shares in the open market.")
    cov = coverage("有多少员工", hit, groups=[["employees", "full-time", "equivalent",
                                              "headcount", "workforce"]])
    assert cov < 0.45, f"通用词把概念覆盖率刷到 {cov}"


def test_generic_token_full_does_not_cover():
    hit = _hit("The plan provides full vesting upon a change in control.")
    cov = coverage("员工人数", hit, groups=[["employees", "full-time", "equivalent",
                                          "headcount", "workforce"]])
    assert cov < 0.45


def test_real_headcount_sentence_still_covers():
    # 正对照：真的写了员工数/员工的段落必须仍算覆盖
    for text in ("As of September 26, 2026, we had approximately 167,000 full-time equivalent employees.",
                 "Our workforce consists of 42,000 associates worldwide.",
                 "Headcount increased 8% year over year."):
        hit = _hit(text)
        cov = coverage("有多少员工", hit, groups=[["employees", "full-time", "equivalent",
                                                  "headcount", "workforce"]])
        assert cov >= 0.45, f"真答案被判成证据不足：{text!r} → {cov}"


def test_equivalent_alone_is_not_headcount():
    # "cash equivalents" 里也有 equivalent，不能当员工证据
    hit = _hit("Cash and cash equivalents were $36.3 billion at year end.")
    cov = coverage("员工有多少人", hit, groups=[["employees", "full-time", "equivalent",
                                             "headcount", "workforce"]])
    assert cov < 0.45


@pytest.mark.skipif(not _has("0000320193"), reason=f"缺少 data/ 里 Apple 的真实申报；{_HOW_TO_FETCH}")
def test_concept_coverage_inflation_is_contained_on_real_corpus():
    """真实 419 chunk 语料上复算：只有含真员工词的段落才允许拿满覆盖。
    修前 39 个 chunk 拿 1.0；修后必须显著下降，且降幅来自通用词而非真答案。"""
    from filinglens import corpus
    f = corpus.load(DATA, "0000320193")
    groups = [["employees", "full-time", "equivalent", "headcount", "workforce"]]
    full = [c for c in f.chunks
            if coverage("有多少员工", Hit(chunk=c, score=1.0, matched=[]),
                        idf=f.index._idf, groups=groups) >= 0.999]
    assert len(full) < 20, f"仍有 {len(full)} 个 chunk 拿满覆盖"
    # 拿满覆盖的段落里必须真的出现 employees/headcount/workforce（不是 time/full）
    word = re.compile(r"\b(?:employees?|headcount|workforce|associates)\b", re.I)
    bad = [c.ref for c in full if not word.search(c.text)]
    assert bad == [], f"这些段落没有员工词却拿满覆盖：{bad[:5]}"


# ---------------- P1-2 年份不是人数 ----------------

def test_year_pair_is_not_headcount():
    """TI 的真实句子：两个年份 + "as a result of employees' elections"。"""
    s = ("As of December 31, 2025 and 2024, as a result of employees' elections "
         "under the plan, the Company recorded compensation cost.")
    assert headcount_number(s) is None, f"把年份当人数了：{headcount_number(s)}"


def test_real_two_year_headcount_still_works():
    # 正对照：真的人数并列仍取本期（第一个）
    assert headcount_number("We had 65,900 and 69,700 employees, respectively.") == "65,900"


def test_comma_separated_headcount_that_looks_like_year():
    # 2,024 employees 是真人数（有千分位），不能按年份丢掉
    assert headcount_number("We employed 2,024 employees in fiscal 2026.") == "2,024 employees"


def test_millions_still_work():
    assert headcount_number("We employed approximately 1.5 million employees.") is not None


def test_fiscal_year_prefix_is_not_headcount():
    s = "For fiscal 2025 and 2024, employee compensation expense was $1.2 billion."
    assert headcount_number(s) is None


# ---------------- P1-3 sql_query 只读 ----------------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE facts (tag TEXT, val REAL)")
    c.execute("INSERT INTO facts VALUES ('Revenue', 1.0)")
    c.commit()
    return c


def test_sql_query_is_read_only():
    c = _conn()
    with pytest.raises(Exception):
        facts.sql_query(c, "DROP TABLE facts")
    # 表还在，说明真没执行
    assert c.execute("SELECT count(*) FROM facts").fetchone()[0] == 1


@pytest.mark.parametrize("sql", [
    "DELETE FROM facts",
    "UPDATE facts SET val = 2",
    "INSERT INTO facts VALUES ('x', 3)",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
])
def test_sql_query_rejects_mutating_statements(sql):
    with pytest.raises(Exception):
        facts.sql_query(_conn(), sql)


def test_sql_query_select_still_works():
    # 正对照：正常查询不受影响
    rows = facts.sql_query(_conn(), "SELECT tag, val FROM facts WHERE val > 0")
    assert [tuple(r) for r in rows] == [("Revenue", 1.0)]


def test_sql_query_cte_select_ok():
    rows = facts.sql_query(_conn(), "WITH x AS (SELECT 1 AS n) SELECT n FROM x")
    assert [tuple(r) for r in rows] == [(1,)]
