"""CLI 的 --traces 必须能吃仓库自带的那份语料。

发现路径：`scripts/e2e.py` 第一次真跑 `cruxline judge --traces data/traces.jsonl`
直接抛 `json.decoder.JSONDecodeError: Extra data: line 2 column 1` ——
CLI 把整个文件当一份 JSON 读，而 `data/traces.jsonl` 是一行一条。
单元测试全绿是因为它们喂 fixtures.TRACES（内存对象），从没走过文件。
"""
from __future__ import annotations

import json
from dataclasses import asdict

from cruxline import fixtures
from cruxline.cli import main


def _write_jsonl(path, n: int = 2):
    path.write_text(
        "\n".join(json.dumps(asdict(t)) for t in fixtures.TRACES[:n]) + "\n",
        encoding="utf-8",
    )


def _write_json_array(path, n: int = 2):
    path.write_text(json.dumps([asdict(t) for t in fixtures.TRACES[:n]]), encoding="utf-8")


def test_judge_accepts_jsonl(tmp_path, capsys):
    p = tmp_path / "traces.jsonl"
    _write_jsonl(p)
    code = main(["judge", "--traces", str(p), "--db", str(tmp_path / "c.db")])
    out = capsys.readouterr().out
    assert code == 0
    assert "通过率" in out


def test_judge_still_accepts_json_array(tmp_path, capsys):
    """正对照：老的 JSON 数组文件不能被这次改动弄坏。"""
    p = tmp_path / "traces.json"
    _write_json_array(p)
    assert main(["judge", "--traces", str(p), "--db", str(tmp_path / "c.db")]) == 0
    assert "通过率" in capsys.readouterr().out


def test_repo_corpus_is_readable_by_the_cli(tmp_path, capsys):
    """仓库自带的 60 条实录必须能直接被 CLI 判定（这条才是 e2e 抓到的那个坑）。"""
    from pathlib import Path
    corpus = Path(__file__).resolve().parents[1] / "data" / "traces.jsonl"
    assert corpus.exists(), corpus
    assert main(["judge", "--traces", str(corpus), "--db", str(tmp_path / "c.db")]) == 0
    out = capsys.readouterr().out
    assert "通过率" in out
    assert out.count("PASS") + out.count("FAIL") >= 60
