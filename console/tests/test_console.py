"""演示台的契约测试：六个面板各自的关键不变式，而不是「接口返回 200」。"""

from __future__ import annotations

import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def app_mod():
    """路由函数本体：并发测试直调它，绕开 TestClient 的 portal 串行。"""
    spec = importlib.util.spec_from_file_location("console_app", ROOT / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client(app_mod):
    return TestClient(app_mod.app)


def test_projects_list_has_six(client):
    body = client.get("/api/projects").json()
    assert len(body) == 6
    assert {p["id"] for p in body} == {"geo", "filing", "audit", "crux", "inbox", "store"}


def test_geo_shares_sum_to_one(client):
    d = client.get("/api/geo", params={"samples": 4}).json()
    assert len(d["prompts"]) == 4
    total = sum(b["share"] for b in d["brands"])
    assert 0.99 <= total <= 1.01          # 份额是「占总提及数」，必须闭合


def test_filing_refuses_without_citations(client):
    d = client.get("/api/filing", params={"q": "CEO 的生日是哪天"}).json()
    assert d["status"] == "insufficient_evidence"
    assert d["citations"] == []


def test_filing_numeric_answer_carries_xbrl_citation(client):
    """单请求契约：数字答案必须带 XBRL 出处（并发正确性见下一条）。"""
    d = client.get("/api/filing", params={"q": "营收多少"}).json()
    assert d["status"] == "ok" and d["kind"] == "metric"
    assert d["citations"][0]["kind"] == "xbrl"


CIK = "0000320193"
# 同一指标的不同问法：任何按问题缓存都 miss，真正复用那条 sqlite 连接
QUESTIONS = ["营收多少", "营业收入是多少", "2025 年营收", "2023 年营收", "总营收"]


def test_filing_concurrent_requests_match_single_thread_baseline(app_mod):
    """跨线程竞态回归：8 线程 × 50 次，每次返回值必须与单线程基线逐值相等。

    旧的 `for _ in range(5)` 是同一线程顺序打 5 次，永远绿（永不并发），
    于是共享 sqlite 连接的竞态继续存在：同一连接 8 线程实测 17 次异常 /
    24 次错值（2019 营收 640.40B 被读成 229.23B，HTTP 仍 200）。
    """
    baseline = {}
    for q in QUESTIONS:
        r = app_mod.filing(q=q, cik=CIK)
        assert r.status_code == 200
        baseline[q] = json.loads(r.body)

    def call(i: int):
        q = QUESTIONS[i % len(QUESTIONS)]
        try:
            return q, json.loads(app_mod.filing(q=q, cik=CIK).body), None
        except Exception as exc:                      # noqa: BLE001 —— 竞态表现为异常
            return q, None, repr(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(8 * 50)))

    errors = [r for r in results if r[2] is not None]
    assert not errors, f"{len(errors)}/{len(results)} 次并发请求抛异常，首个：{errors[0][2]}"
    bad = [(q, body) for q, body, _ in results if body != baseline[q]]
    assert not bad, (
        f"{len(bad)}/{len(results)} 次并发返回值与单线程基线不同，"
        f"首个问题 {bad[0][0]!r}：{bad[0][1]['text'] if bad[0][1] else None}")
    assert all(body["status"] == "ok" and body["citations"][0]["kind"] == "xbrl"
               for _, body, _ in results)


def test_audit_reports_exceptions_and_status(client):
    d = client.get("/api/audit").json()
    assert d["status"] == "attention_required"
    assert len(d["exceptions"]) >= 5
    assert {s["name"] for s in d["steps"]} >= {"bank_recon", "ar_aging", "revenue_cutoff"}


def test_crux_veto_beats_weighted_score(client):
    d = client.get("/api/crux").json()
    c3 = next(c for c in d["cases"] if c["id"] == "c3")
    assert c3["score"] == 0.75 and c3["passed"] is False
    assert c3["vetoed"] == ["no_tool_error"]


def test_crux_calibration_matches_human_labels(client):
    d = client.get("/api/crux").json()
    assert d["calibration"]["kappa"] == 1.0
    assert d["calibration"]["ok"] is True


def test_inbox_blocks_non_allowlisted_sender(client):
    d = client.get("/api/inbox").json()
    mallory = next(m for m in d["messages"] if "mallory" in m["sender"])
    assert mallory["outcome"] == "blocked"


def test_inbox_external_reply_needs_approval(client):
    d = client.get("/api/inbox").json()
    external = [m for m in d["messages"] if m["external"] and m["outcome"] != "blocked"]
    assert external and all(m["outcome"] == "approval" for m in external)
    assert all(m["approval_id"] for m in external)


def test_store_blocks_missing_permission_and_is_idempotent(client):
    d = client.get("/api/store").json()
    blocked = [e for e in d["executions"] if e["blocked"]]
    assert len(blocked) == 1 and blocked[0]["agent"] == "deck-research"
    dup = [e for e in d["executions"] if e["duplicate"]]
    assert len(dup) == 1
    # 六次调用里两次被拦/重投不计费：invoice 5¢ ×2 + deck 90¢ + cfo 900¢ = 1000¢
    assert d["statement"]["gross_cents"] == 1000
    assert d["statement"]["platform_cents"] == 200
    assert d["statement"]["developer_cents"] == 800


def test_page_serves_console_shell(client):
    html = client.get("/").text
    assert "startup" in html and "/api/geo" in html
