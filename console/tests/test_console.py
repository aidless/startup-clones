"""演示台的契约测试：六个面板各自的关键不变式，而不是「接口返回 200」。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client():
    spec = importlib.util.spec_from_file_location("console_app", ROOT / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return TestClient(mod.app)


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
    d = client.get("/api/filing", params={"q": "营收多少"}).json()
    assert d["status"] == "ok" and d["kind"] == "metric"
    assert d["citations"][0]["kind"] == "xbrl"


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
