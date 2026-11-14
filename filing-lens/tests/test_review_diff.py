"""复核差异表生成器的双向测试（AGENTS.md 第 21/37 条）。

每条检查两段：
1) 注入一处真缺陷 → 必须抓到（否则是装饰）；
2) 原始样本原样再跑 → 必须不报（否则是假阳，合伙人看到一条假警报就不会翻第二页）。

两个真实样本都不是造的：Broadcom 那句「$27,537 million in net cash provided by
operating activities」在原文里数在科目名之前；Meta 的「Services net sales
decreased $770 million, or 28%」是分部口径。第一版检查在两者上都栽了。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "review_diff", ROOT / "scripts" / "review_diff.py")
    mod = importlib.util.module_from_spec(spec)
    # dataclass 需要模块已在 sys.modules 里（否则 _is_type 取 __module__ 拿到 None）
    sys.modules["review_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


rd = _load()
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def broadcom():
    return rd.build("0001730168", DATA)


@pytest.fixture(scope="module")
def meta():
    return rd.build("0001318605", DATA)


# ---------- 1. 现金流量口径：双向 ----------

def test_real_broadcom_cash_sentence_is_not_flagged(broadcom):
    """原句同时出现余额与流量，但主语正确 → 不许报。"""
    mism = [f for f in broadcom.findings
            if f.check == "现金流量口径" and f.severity == "mismatch"]
    assert mism == [], [f.what for f in mism]


def test_injected_cash_defect_is_flagged():
    """把 Broadcom 那句的经营现金流换成现金余额 → 必须抓，且指出对不上的两个数。"""
    rep = rd.build("0001730168", DATA, inject=(
        "27,537 million in net cash provided by operating activities",
        "16,178 million in net cash provided by operating activities",
    ))
    mism = [f for f in rep.findings
            if f.check == "现金流量口径" and f.severity == "mismatch"]
    assert len(mism) == 1
    assert "16,178" in mism[0].what
    assert "27.54B" in mism[0].what          # 拿 XBRL 真值对照
    assert mism[0].ref.endswith("Item 7¶188")


# ---------- 2. 百分比：只认合计口径 ----------

def test_segment_level_percent_is_not_flagged(meta):
    """Meta「Services net sales decreased $770 million, or 28%」是分部口径 → 不许报。"""
    bad = [f for f in meta.findings
           if f.check == "正文百分比" and f.severity == "mismatch"
           and "or 28%" in f.what]
    assert bad == []


def test_percent_check_only_reports_totality_subject(meta):
    for f in meta.findings:
        if f.check == "正文百分比" and f.severity == "mismatch":
            assert "total" in f.what.lower() or "合计" in f.what


# ---------- 3. 契约：每条都得能追 ----------

def test_every_finding_has_a_traceable_ref(broadcom):
    for f in broadcom.findings:
        assert f.ref and f.ref != "—", f
        assert ("#Item" in f.ref) or f.ref.startswith("XBRL:"), f.ref


def test_uncovered_items_are_declared_not_guessed(broadcom):
    """没有 segment 数据/只有一份年报时，必须写进 skipped，而不是编一条结论。"""
    names = [n for n, _ in broadcom.skipped]
    assert any("风险因素年度差异" in n for n in names)
    for f in broadcom.findings:
        assert "无法核" not in f.what


# ---------- 4. 金额解析 ----------

@pytest.mark.parametrize("text,expect", [
    ("totaled $145.1 billion", 145.1e9),
    ("$27,537 million in net cash", 27.537e9),
    ("approximately $1.2 trillion", 1.2e12),
])
def test_money_parse(text, expect):
    vals = rd._money_values(text)
    assert vals and abs(vals[0][0] - expect) / expect < 1e-6


def test_inject_refuses_missing_anchor():
    with pytest.raises(SystemExit):
        rd.build("0001730168", DATA, inject=("这句话原文里不存在", "x"))


# ---------- 7. 跨年比较 / 整元金额：小盘 10-K 的两个真实坑 ----------

def _conn(rows):
    """最小 facts 表：`_latest` 只查 tag/fy/val/unit/form/end 六列。"""
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row  # `_latest` 用 dict(row) 还原 Fact
    c.execute("CREATE TABLE facts (tag TEXT, fy INTEGER, val REAL, unit TEXT,"
              " form TEXT, end TEXT, filed TEXT, fp TEXT)")
    c.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?)", rows)
    return c


def _filing(conn, texts):
    from types import SimpleNamespace
    return SimpleNamespace(conn=conn,
                           chunks=[SimpleNamespace(text=t, ref=f"fake#¶{i}")
                                   for i, t in enumerate(texts)])


def test_cash_caliber_never_compares_two_different_years():
    """XERIANT 实测：CFO 取到 2026、现金取到 2021（该公司后来换了标签名），
    表里于是出现「经营现金流 2026 = -791,756，现金及等价物 2021 = 962,540（差 1.8×）」
    —— 两个不同年份的数相减，这个「倍数」没有任何含义，而它印在交付物第一行。
    """
    conn = _conn([
        ("NetCashProvidedByUsedInOperatingActivities", 2026, -791756.0, "USD", "10-K", "2026-06-30", "", "FY"),
        ("CashAndCashEquivalentsAtCarryingValue", 2021, 962540.0, "USD", "10-K", "2021-06-30", "", "FY"),
    ])
    rep = rd.Report("0001481504", entity="XERIANT", period="2026-06-30")
    rd.check_cash_caliber(_filing(conn, ["cash flow from operations was negative."]), rep)
    said = " ".join(x.what + x.ref for x in rep.findings) + " ".join(s for _, s in rep.skipped)
    assert "2021" not in said, f"仍然拿 2021 的现金去比 2026 的经营现金流：{said}"
    assert any("现金" in s for _, s in rep.skipped), "缺同年现金标签时要照实说缺，不能跨年凑一个"


def test_cash_caliber_prefers_the_restricted_cash_tag_in_the_same_year():
    """正对照的另一面：同年的「含受限现金」标签必须被认到，不能因为改名就说「缺」。"""
    conn = _conn([
        ("NetCashProvidedByUsedInOperatingActivities", 2026, 4000000.0, "USD", "10-K", "2026-06-30", "", "FY"),
        ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 2026, 22700000.0,
         "USD", "10-K", "2026-06-30", "", "FY"),
    ])
    rep = rd.Report("0001836754", entity="Legacy", period="2026-06-30")
    rd.check_cash_caliber(_filing(conn, ["no sentence here"]), rep)
    assert rep.findings, "同年有含受限现金的标签，却报「缺科目」"
    assert "22.7M" in rep.findings[0].what


def test_dollar_amounts_without_a_scale_word_are_read():
    """PAID INC（20.7M 营收）正文写 `$ 20,690,000`，不带 million/billion；
    旧正则只认带量级词的金额，于是整项报「正文没有同量级表述」——
    对小盘 10-K（我们的目标客户全是这类）等于这道检查整项空转。
    """
    conn = _conn([
        ("RevenueFromContractWithCustomerExcludingAssessedTax", 2025, 20690235.0,
         "USD", "10-K", "2025-12-31", "", "FY"),
    ])
    rep = rd.Report("0001017655", entity="PAID", period="2025-12-31")
    rd.check_text_vs_xbrl(
        _filing(conn, ["Revenue increased to $ 20,690,000 for the year ended December 31, 2025."]),
        rep)
    assert rep.findings, [s for _, s in rep.skipped]
    assert "同量级" in rep.findings[0].what


def test_yoy_sign_crossing_is_flagged_as_meaningless():
    """PAID INC 实测：CFO 2024 = 447,643、2025 = -53,171，表里印「-111.9%」
    并标 info，「与正文披露的百分比核对一次」——正文不可能写 -112%，
    复核员照这条去核对只会白跑一趟。基数跨零的百分比必须自己先声明无含义。
    """
    conn = _conn([
        ("NetCashProvidedByUsedInOperatingActivities", 2024, 447643.0, "USD", "10-K", "2024-12-31", "", "FY"),
        ("NetCashProvidedByUsedInOperatingActivities", 2025, -53171.0, "USD", "10-K", "2025-12-31", "", "FY"),
    ])
    rep = rd.Report("0001017655", entity="PAID", period="2025-12-31")
    rd.check_yoy_negative_base(_filing(conn, ["no sentence"]), rep)
    hits = [x for x in rep.findings if x.check == "同比口径"]
    assert hits, "跨零的同比一条都不报"
    assert hits[0].severity == "look", f"基数跨零却当成普通 info：{hits[0]}"
    assert "无含义" in hits[0].what or "没有含义" in hits[0].what, hits[0].what


def test_headcount_accepts_faculty_wording():
    """Legacy Education 原文：「we had approximately 120 full-time faculty, …
    approximately 180 part-time faculty」——它没有 employees 这个词，
    旧实现于是报「未出现可解析的员工数句式」，而人数就在那句话里。
    """
    rep = rd.Report("0001836754", entity="Legacy", period="2026-06-30")
    rd.check_headcount_year(_filing(None, [
        "As of June 30, 2026, we had approximately 120 full-time faculty, "
        "including 16 program directors, as well as approximately 180 part-time faculty."]), rep)
    said = " ".join(x.what for x in rep.findings)
    assert "120" in said, [s for _, s in rep.skipped]


def test_cash_caliber_does_not_print_a_flow_over_balance_ratio():
    """余额（存量）除流量（期间）得到的「倍数」没有经济含义：
    XERIANT 印出「经营现金流 -791,756，现金 87,594（差 10.0×）」，
    10 倍这个数既不是覆盖率也不是周转，只会让复核员以为我们算错了。
    """
    conn = _conn([
        ("NetCashProvidedByUsedInOperatingActivities", 2026, -791756.0, "USD", "10-K", "2026-06-30", "", "FY"),
        ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 2026, 87594.0,
         "USD", "10-K", "2026-06-30", "", "FY"),
    ])
    rep = rd.Report("0001481504", entity="XERIANT", period="2026-06-30")
    rd.check_cash_caliber(_filing(conn, ["no sentence"]), rep)
    what = rep.findings[0].what
    assert "×" not in what, what
    assert "87,594" in what or "87.6K" in what or "87,594 USD" in what, what


def test_text_percent_skips_when_the_base_crosses_zero():
    """PAID INC 实测：正文百分比这一项把「正文称 decreased 20%」判成 mismatch，
    理由是「XBRL 实算 -111.9%」—— 而基数由正转负时公式算出的百分比本身无含义，
    拿它去否定正文，是在用一把坏的尺判客户错。
    """
    conn = _conn([
        ("NetCashProvidedByUsedInOperatingActivities", 2024, 447643.0, "USD", "10-K", "2024-12-31", "", "FY"),
        ("NetCashProvidedByUsedInOperatingActivities", 2025, -53171.0, "USD", "10-K", "2025-12-31", "", "FY"),
    ])
    rep = rd.Report("0001017655", entity="PAID", period="2025-12-31")
    rd.check_text_percent(_filing(conn, [
        "Net cash provided by operating activities decreased 20% for fiscal 2025."]), rep)
    assert not [x for x in rep.findings if x.severity == "mismatch"], \
        [x.what for x in rep.findings]
    assert any("跨零" in s for _, s in rep.skipped), [s for _, s in rep.skipped]
