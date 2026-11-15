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


def _needs(cik: str) -> Path:
    """`data/` 是被 .gitignore 掉的 164MB SEC 语料，干净检出里没有它。

    只跳过真正要读真实申报的用例——本文件里那些拿合成 sqlite 跑的用例
    （`_conn()` + `rd.check_*`）不依赖 data/，必须继续跑。

    补齐：
        cd filing-lens && python3 scripts/batch_bench.py
    （只想用本地已经抓下来的文件时加 `--no-fetch`）
    """
    if not (DATA / f"{cik}_facts.json").exists() or not list(DATA.glob(f"{cik}_10k_*.htm")):
        pytest.skip(
            f"缺少 {DATA}/{cik}_10k_*.htm 与 {cik}_facts.json；"
            "先跑 `cd filing-lens && python3 scripts/batch_bench.py` 抓回 22 份 10-K"
            "（只用本地已有文件：python3 scripts/batch_bench.py --no-fetch）")
    return DATA


@pytest.fixture(scope="module")
def broadcom():
    return rd.build("0001730168", _needs("0001730168"))


@pytest.fixture(scope="module")
def meta():
    return rd.build("0001318605", _needs("0001318605"))


# ---------- 1. 现金流量口径：双向 ----------

def test_real_broadcom_cash_sentence_is_not_flagged(broadcom):
    """原句同时出现余额与流量，但主语正确 → 不许报。"""
    mism = [f for f in broadcom.findings
            if f.check == "现金流量口径" and f.severity == "mismatch"]
    assert mism == [], [f.what for f in mism]


def test_injected_cash_defect_is_flagged():
    """把 Broadcom 那句的经营现金流换成现金余额 → 必须抓，且指出对不上的两个数。"""
    rep = rd.build("0001730168", _needs("0001730168"), inject=(
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
        rd.build("0001730168", _needs("0001730168"), inject=("这句话原文里不存在", "x"))


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


# ---------- 2b. 百分比必须绑在三件事上：主语、期间、子句 ----------
# 2026-11-14 语料普查（scripts/check_coverage.py）发现三处真假阳，全部是「百分比
# 出现在含 total revenue 的句子里，但它说的是别的东西」：
#   Cisco Item 7¶54「Within total revenue, product revenue increased by 16%」——分部口径
#   Cisco Item 7¶65「total revenue increased by 18%」——那是**第四季度**同比，不是全年
#   Meta  Item 7¶182「increased 17%, 19%, and 17% between the third and fourth quarters」
#                        ——季度间环比（季节性例子），与年度同比无关
# 三条都属于「句子对了、绑错了对象」，只看关键词在不在句子里是挡不住的。

@pytest.fixture(scope="module")
def cisco():
    return rd.build("0000858877", _needs("0000858877"))


@pytest.fixture(scope="module")
def meta_platforms():
    return rd.build("0001326801", _needs("0001326801"))


def test_quarterly_percent_is_not_compared_to_annual(cisco):
    """第四季度同比 18% 不能拿去比全年同比 11.8%。"""
    bad = [f for f in cisco.findings
           if f.check == "正文百分比" and f.severity == "mismatch"]
    assert bad == [], [f.what for f in bad]


def test_category_percent_inside_total_revenue_is_not_flagged(cisco):
    """「Within total revenue, product revenue increased by 16%」是产品口径。"""
    bad = [f for f in cisco.findings
           if f.check == "正文百分比" and f.severity == "mismatch" and "16%" in f.what]
    assert bad == []


def test_sequential_seasonality_percent_is_not_flagged(meta_platforms):
    """季度间环比（17%/19%/17%）不是年度同比。"""
    bad = [f for f in meta_platforms.findings
           if f.check == "正文百分比" and f.severity == "mismatch"]
    assert bad == [], [f.what for f in bad]


def test_injected_percent_defect_is_still_flagged():
    """正对照：把全年同比那处的 12% 改成 42% → 必须抓，别把守卫做成一刀切屏蔽。"""
    rep = rd.build("0000858877", _needs("0000858877"), inject=(
        "an increase of 12% compared with fiscal 2025",
        "an increase of 42% compared with fiscal 2025",
    ))
    mism = [f for f in rep.findings
            if f.check == "正文百分比" and f.severity == "mismatch"]
    assert len(mism) == 1, [f.what for f in mism]
    assert "42%" in mism[0].what


PROSPECTS = ROOT / "data-prospects"


@pytest.fixture(scope="module")
def paid():
    return rd.build("0001017655", PROSPECTS)


@pytest.fixture(scope="module")
def legacy():
    return rd.build("0001836754", PROSPECTS)


def test_bare_revenues_with_matching_dollar_delta_binds(paid):
    """小盘写法：「Revenues increased $2,122,710 or 11%」主语不带 total/net。

    金额增量与 XBRL 算出的当年增量一致，就足以证明这是合计口径——
    光看主语会把这句整条漏掉（小盘 MD&A 的典型写法）。
    """
    hits = [f for f in paid.findings if f.check == "正文百分比"]
    assert any("11%" in f.what for f in hits), [f.what for f in hits]


def test_expense_ratio_is_never_a_revenue_claim(legacy):
    """「As a percentage of revenue, ... expense increased from 53.4% to 53.6%」

    这是费用率（水平变化），不是营收同比。判成 mismatch 就是拿坏尺判客户错。
    """
    bad = [f for f in legacy.findings if f.check == "正文百分比" and f.severity == "mismatch"]
    assert bad == [], [f.what for f in bad]
    assert not any("53.4%" in f.what for f in legacy.findings)


def test_risk_diff_compares_a_real_previous_year(legacy):
    """Legacy 在 data-prospects 里有 2025 与 2026 两期 → 这一项必须真比，不是 skipped。"""
    hits = [f for f in legacy.findings if f.check == "风险因素年度差异"]
    assert hits, "风险因素年度差异没出结果"
    assert "2025-06-30 → 2026-06-30" in hits[0].ref
    assert "新增/改写 0 段" not in hits[0].what, hits[0].what
    assert not [s for s in legacy.skipped if s[0] == "风险因素年度差异"]


def test_risk_diff_says_how_to_get_the_previous_year():
    """只有一份时不能只说「无法比较」，要告诉人怎么补上（--fetch-prior）。"""
    rep = rd.build("0001481504", PROSPECTS)
    sk = [s for s in rep.skipped if s[0] == "风险因素年度差异"]
    if sk:                     # 该 CIK 若已补抓上年，则这一项直接出结果
        assert "--fetch-prior" in sk[0][1], sk[0]
