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
