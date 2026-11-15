"""百分比绑定的单元与集成测试（AGENTS.md 第 21/37 条：能红，且不乱给分）。

背景：`check_text_percent` 是复核差异表的主力项，但 2026-11-14 的语料普查
（`scripts/check_coverage.py` + 漏斗计数）显示，22 份 10-K 里 119 处百分比表述
只有 8 句真正绑到合计口径上。放宽就出假阳（下面四个反例都是真实原文），
收紧就整项空转——判据必须落在「主语 + 期间 + 子句」三件事上。

四个反例都来自 real filings，不是造的：
  Tesla  「Services net sales decreased $770 million, or 28%」        分部（Services）
  Intel  「Data Center net revenue of $16.6 billion increased by 32%」 分部（Data Center）
  Meta   「RL revenue in 2025 increased $61 million, or 3%」          分部（Reality Labs）
  Cisco  「For the fourth quarter ... total revenue increased by 18%」 期间（季度）
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
    sys.modules["review_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


rd = _load()
DATA = ROOT / "data"


def _pct_pos(sent: str) -> int:
    return sent.index("%")


@pytest.mark.parametrize("sent", [
    "Total revenue was $63.3 billion, an increase of 12% compared with fiscal 2025.",
    "Net sales increased 3% to $87.0 billion versus the prior year.",
    "Net revenue was $24.1 billion, up 12%.",
])
def test_total_subject_statement_binds(sent):
    assert rd._pct_bound_to_total(sent, _pct_pos(sent)) is True


@pytest.mark.parametrize("sent", [
    "Services net sales decreased $770 million, or 28%.",
    "Data Center net revenue of $16.6 billion increased by 32% compared to 2024.",
    "RL revenue in 2025 increased $61 million, or 3%, compared to 2024.",
    "Client and Gaming net revenue of $14.6 billion in 2025 increased by 51%.",
])
def test_segment_subject_does_not_bind(sent):
    assert rd._pct_bound_to_total(sent, _pct_pos(sent)) is False


def test_quarterly_sentence_is_rejected_by_scope():
    sent = ("For the fourth quarter of fiscal 2026, as compared with the fourth quarter of "
            "fiscal 2025, total revenue increased by 18% to $17.3 billion.")
    assert rd._quarter_scoped(sent, sent.index("18%"))


@pytest.mark.parametrize("sent", [
    "Total revenue increased 17%, 19%, and 17% between the third and fourth quarters.",
    "Revenue grew 4% sequentially.",
])
def test_sequential_sentence_is_rejected_by_scope(sent):
    assert rd._quarter_scoped(sent, sent.index("%"))


def test_quarter_word_about_the_source_is_not_a_period():
    """PAID INC：quarter 讲的是收入来源（fourth quarter increase in shipping…），不是期间。"""
    sent = ("Revenues increased $2,122,710 or 11% in 2025 primarily from a result of the "
            "fourth quarter increase in shipping coordination and label generation services.")
    assert rd._quarter_scoped(sent, sent.index("11%")) is False


def test_percent_forms_all_parse():
    """动词式、名词式、口语式三种写法都要读到数（只认动词式会静默丢主力句式）。"""
    cases = {
        "Total revenue increased by 12% compared with 2025.": 12.0,
        "Total revenue was $63.3 billion, an increase of 12% compared with 2025.": 12.0,
        "Net revenue was $24.1 billion, up 12%.": 12.0,
    }
    for sent, expect in cases.items():
        ms = list(rd._PCT.finditer(sent))
        assert ms, sent
        assert rd._pct_value(ms[0]) == expect, (sent, [m.group(0) for m in ms])


@pytest.fixture(scope="module")
def cisco():
    return rd.build("0000858877", DATA)


def test_cisco_total_revenue_percent_is_reported_as_checked(cisco):
    """正对照：Cisco 全年同比确实核到了（info），说明这一项在这份文件上没空转。"""
    hits = [f for f in cisco.findings if f.check == "正文百分比"]
    assert hits, [f.check for f in cisco.findings]
    assert all(f.severity == "info" for f in hits), [f.what for f in hits]
