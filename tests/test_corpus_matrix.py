"""语料矩阵的两条回归：真实文件都要读得通，已记录的边界不许悄悄扩大。

`scripts/corpus_matrix.py` 跑全部 22 份要两分钟，不适合放进每次提交的套件；
所以这里只用 `--only` 跑两份**有代表性的**：

1. `0000320193`（Apple）：正常的结构化 10-K —— 章节识别必须成功（≥15 个 Item）。
2. `0000050863`（Intel）：**已记录的边界** —— 正文不用 "Item N." 做标题
   （只有目录页写 Item，正文是 "Risk Factors" 这种裸标题），所以 `split_sections`
   整篇退化成一段 `Full Text`（`edgar.py:135-140` 的 `MIN_BODY_RATIO` 分支）。
   这条边界是设计选择：检索照常工作，只是失去 Item 归属。

为什么要钉住它：这个退化分支一旦对**第二份**文件生效，说明解析退化了，而输出
仍然是「解析成功、能回答」，只是答案从此没有 Item 归属——不写死就永远发现不了。
全量矩阵的读数留在 `docs/corpus-matrix.json`，`--baseline` 可以逐份比对漂移。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLE = "0000320193"
INTEL = "0000050863"
FULL_MATRIX = ROOT / "docs" / "corpus-matrix.json"


def _matrix(*args: str) -> dict:
    p = subprocess.run([sys.executable, "scripts/corpus_matrix.py", "--json", *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-800:]
    return json.loads(p.stdout)


def test_two_representative_files_parse():
    data = _matrix("--only", f"{APPLE},{INTEL}")
    rows = {r["cik"]: r for r in data["rows"]}
    assert set(rows) == {APPLE, INTEL}
    for cik, row in rows.items():
        assert row["ok"], f"{cik} 解析失败：{row['error']}"
        assert row["facts"], f"{cik} 没有 XBRL"
        assert row["chunks"] >= 200, f"{cik} 只切出 {row['chunks']} 段"


def test_apple_keeps_item_structure():
    rows = {r["cik"]: r for r in _matrix("--only", APPLE)["rows"]}
    assert rows[APPLE]["sections"] >= 15, "Apple 的 Item 结构识别退化"


def test_intel_is_the_recorded_full_text_fallback():
    """Intel 退化成 Full Text 是**已知边界**；这条同时钉住「不许再多一份」。"""
    rows = {r["cik"]: r for r in _matrix("--only", INTEL)["rows"]}
    assert rows[INTEL]["sections"] == 1, "Intel 的退化形态变了，先说明原因再改这条断言"
    assert rows[INTEL]["chunks"] >= 500, "整篇当一段时也不该只剩几百字"


def test_full_matrix_baseline_is_present_and_self_consistent():
    """全量基线必须存在且自洽：22 份、全 ok、全带 XBRL、只有一份是退化形态。"""
    data = json.loads(FULL_MATRIX.read_text(encoding="utf-8"))
    rows = data["rows"]
    assert len(rows) == 22, f"基线里有 {len(rows)} 份，期望 22"
    assert all(r["ok"] for r in rows), [r["cik"] for r in rows if not r["ok"]]
    assert all(r["facts"] for r in rows)
    fallback = [r["cik"] for r in rows if r.get("sections", 0) <= 2]
    assert fallback == [INTEL], f"退化形态的文件变成了 {fallback}，先解释再修基线"
