"""上一期 10-K 的取用逻辑（风险因素年度差异的前提）。

两个坑：
1. `prior_10k` 只挑 reportDate 早于当前期的，不能把当前期当上年（diff 恒为 0）；
2. `corpus.load` 只给 tag 时 `sorted()` 取最后一个＝最新一期，必须能按 period 指定，
   否则两期读到同一份文件，输出「上年 2026-06-30、本年 2026-06-30，新增 0 段」——
   看起来是「风险没变」，其实是没比。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens import corpus, ingest  # noqa: E402


def _fake(*filings):
    return [{"cik": "0000000001", "period": p, "filed": f, "accession": a,
             "html_url": "u", "facts_url": "f", "company": "X"}
            for p, f, a in filings]


def test_prior_10k_skips_the_current_period(monkeypatch):
    monkeypatch.setattr(ingest, "_tenks", lambda cik: _fake(
        ("2026-06-30", "2026-09-01", "a-1"),
        ("2025-06-30", "2025-09-01", "a-2"),
        ("2024-06-30", "2024-09-01", "a-3"),
    ))
    got = ingest.prior_10k("1", "2026-06-30")
    assert got["period"] == "2025-06-30"
    assert got["accession"] == "a-2"


def test_prior_10k_raises_when_there_is_nothing_earlier(monkeypatch):
    monkeypatch.setattr(ingest, "_tenks", lambda cik: _fake(("2026-06-30", "2026-09-01", "a-1")))
    with pytest.raises(ingest.IngestError):
        ingest.prior_10k("1", "2026-06-30")


def test_load_by_period_picks_that_year(tmp_path):
    (tmp_path / "0000000001_10k_2025-06-30.htm").write_text("<html>old</html>")
    (tmp_path / "0000000001_10k_2026-06-30.htm").write_text("<html>new</html>")
    assert corpus.load(tmp_path, "0000000001").period == "2026-06-30"       # 默认最新
    assert corpus.load(tmp_path, "0000000001", "2025-06-30").period == "2025-06-30"
    with pytest.raises(FileNotFoundError):
        corpus.load(tmp_path, "0000000001", "2020-06-30")
