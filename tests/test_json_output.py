"""`--json` 的契约：四个「查询型」子命令必须能吐结构化结果。

为什么只要求四个：`agent-inbox` 与 `agent-store` 目前只有 `demo`，没有可查询的东西
——给 demo 加 `--json` 是给演示稿套接口形状，不是给调用方用。等它们有了查询命令
（inbox 的 `route`、store 的 `statement`）再一起纳入，宁可缺一条，不造假一条。

每条都断言两层：
1. stdout **整体**是一个 JSON 对象（不是「JSON 后面跟几行人话」）；
2. 关键字段在，且能用它重建人读版本里的那个数 —— 这是「同一份结果两种视图」的
   最低要求，否则 `--json` 与文本各算一次，迟早分叉。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILING = ROOT / "filing-lens"
CIK = "0000320193"


def _run(project: str, *args: str) -> dict:
    p = subprocess.run([sys.executable, "-m", *args],
                       cwd=ROOT / project, capture_output=True, text=True, timeout=300)
    assert p.returncode in (0, 1), p.stderr[-800:]
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"stdout 不是纯 JSON：\n{p.stdout[:400]}")


def test_filing_ask_json_keeps_answer_and_citations():
    data = _run("filing-lens", "filinglens.cli", "ask", "What was net income?",
                "--html", str(FILING / "data" / f"{CIK}_10k_2026-09-26.htm"),
                "--facts", str(FILING / "data" / f"{CIK}_facts.json"), "--json")
    assert data["question"] == "What was net income?"
    assert data["status"] in {"ok", "no_data", "insufficient_evidence"}
    assert data["citations"], "数字题必须带出处，--json 里也不能丢"
    assert {"kind", "ref"} <= set(data["citations"][0])


def test_geo_report_json_matches_the_markdown_numbers(tmp_path):
    db = tmp_path / "g.db"
    _run("geo-radar", "georadar.cli", "run", "--brand", "Acme", "--category", "AI SRE",
         "--competitors", "Traversal", "--repeat", "2", "--db", str(db), "--json")
    # run --json 必须给 run_id，否则调用方拿不到 report 的入参
    run = _run("geo-radar", "georadar.cli", "run", "--brand", "Acme", "--category", "AI SRE",
               "--competitors", "Traversal", "--repeat", "2", "--db", str(db), "--json")
    assert run["run_id"].startswith("run-")
    rep = _run("geo-radar", "georadar.cli", "report", "--db", str(db),
               "--run-id", run["run_id"], "--json")
    assert rep["brand"] == "Acme"
    acme = [b for b in rep["brands"] if b["name"] == "Acme"]
    assert acme, "报表里必须有品牌行"
    # 交接的判据是「同一个品牌的同一个数」，不是合计提及数
    assert acme[0]["mentions"] == [b for b in run["brands"] if b["name"] == "Acme"][0]["mentions"]


def test_crux_judge_json_carries_verdicts_and_pass_rate():
    data = _run("cruxline", "cruxline.cli", "judge", "--traces", "data/traces.jsonl",
                "--db", ":memory:", "--json")
    assert data["total"] >= 60
    assert 0.0 <= data["pass_rate"] <= 1.0
    assert len(data["verdicts"]) == data["total"]
    v = data["verdicts"][0]
    assert {"case_id", "score", "passed"} <= set(v)
    # 通过率必须由逐条结果算出来，不是另算一遍
    recomputed = sum(x["passed"] for x in data["verdicts"]) / data["total"]
    assert abs(recomputed - data["pass_rate"]) < 1e-6, "通过率必须由逐条结果算出，不能另算一遍"


def test_audit_run_json_carries_exceptions():
    data = _run("audit-loop", "auditloop.cli", "run", "--json")
    assert data["entity"]
    assert data["steps"], "至少要报出跑了哪些程序"
    assert isinstance(data["exceptions"], list)
    names = {s["name"] for s in data["steps"]}
    assert {"bank_recon", "revenue_cutoff"} <= names, names
    assert all(isinstance(s["findings"], int) for s in data["steps"])


def test_judge_cli_uses_the_agent_rubric_by_default():
    """CLI 判 agent 轨迹时必须用 `agent_rubric()`，而不是写死在 `judge.py` 的通用五条。

    旧行为实测：默认 rubric 下 `judge --traces data/traces.jsonl` 报 34/60 通过，
    而 README 与 `scripts/real_traces.py` 说 59/60 —— 同一批轨迹两个数，
    差别只在「用了哪套 rubric」，命令行从来没走过产品自己那套。
    """
    data = _run("cruxline", "cruxline.cli", "judge", "--traces", "data/traces.jsonl",
                "--db", ":memory:", "--json")
    assert data["rubric"] == "agent", data.get("rubric")
    assert data["passed"] == 59, f"实测 {data['passed']}/60，与 real_traces.py 的 59 不一致"
    assert data["pass_rate"] > 0.98


def test_judge_cli_can_ask_for_the_generic_rubric():
    """正对照：显式要通用 rubric 时必须真的换过去（否则上面那条就等于写死）。"""
    data = _run("cruxline", "cruxline.cli", "judge", "--traces", "data/traces.jsonl",
                "--db", ":memory:", "--rubric", "default", "--json")
    assert data["rubric"] == "default"
    assert data["passed"] < 59, "两套 rubric 给出同一个数，说明 --rubric 没生效"
