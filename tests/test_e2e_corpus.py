"""e2e 语料选择的判据（AGENTS.md 第 21 条：先写会红的测试）。

为什么要这一层：`scripts/e2e.py` 原来把 CIK 写死成 Apple（`0000320193`），
而 Apple 那两份文件在 `filing-lens/data/` 里，`data/` 是被 .gitignore 掉的
164MB 语料。别人 clone 下来跑 e2e 只会得到一条 `FileNotFoundError`。
入库的只有 `filing-lens/data-prospects/`（三家小盘客户）。

判据：
1. 有 Apple（22 份语料在位）→ 用 data/ + Apple；
2. 没有 data/ 但有入库的 XERIANT（data-prospects/）→ 退到它，链路照样真跑；
3. 两边都没有 → 明确报错并说清怎么补，不许静默跑一份空数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _e2e():
    import importlib

    import e2e
    return importlib.reload(e2e)


def _make(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("<html></html>", encoding="utf-8")


def test_prefers_the_tracked_prospects_when_data_is_absent(tmp_path):
    _make(tmp_path, "filing-lens/data-prospects/0001481504_10k_2026-06-30.htm")
    _make(tmp_path, "filing-lens/data-prospects/0001481504_facts.json")
    mod = _e2e()
    data_dir, cik, period = mod.resolve_corpus(tmp_path)
    assert data_dir == tmp_path / "filing-lens" / "data-prospects"
    assert cik == "0001481504"
    assert period == "2026-06-30"


def test_uses_the_full_corpus_when_apple_is_present(tmp_path):
    _make(tmp_path, "filing-lens/data/0000320193_10k_2026-09-26.htm")
    _make(tmp_path, "filing-lens/data/0000320193_facts.json")
    _make(tmp_path, "filing-lens/data-prospects/0001481504_10k_2026-06-30.htm")
    mod = _e2e()
    data_dir, cik, period = mod.resolve_corpus(tmp_path)
    assert data_dir == tmp_path / "filing-lens" / "data"
    assert cik == "0000320193"
    assert period == "2026-09-26"


def test_says_how_to_fetch_the_corpus_when_neither_is_there(tmp_path):
    mod = _e2e()
    with pytest.raises(SystemExit) as exc:
        mod.resolve_corpus(tmp_path)
    msg = str(exc.value)
    assert "batch_bench" in msg, msg
    assert "data-prospects" in msg, msg


def test_the_step_argv_can_carry_the_chosen_data_dir(tmp_path):
    _make(tmp_path, "filing-lens/data-prospects/0001481504_10k_2026-06-30.htm")
    _make(tmp_path, "filing-lens/data-prospects/0001481504_facts.json")
    mod = _e2e()
    data_dir, cik, period = mod.resolve_corpus(tmp_path)
    html = data_dir / f"{cik}_10k_{period}.htm"
    facts = data_dir / f"{cik}_facts.json"
    args = mod._fmt(["--data", "{data}", "--cik", "{cik}"], tmp_path, data_dir,
                    cik, html, facts)
    assert args == ["--data", str(data_dir), "--cik", "0001481504"]
