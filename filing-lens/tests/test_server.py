"""演示服务的契约测试：数字走 XBRL、正文带出处、没证据就拒答、缺文件要说人话。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens import fixtures  # noqa: E402


def _load_server():
    spec = importlib.util.spec_from_file_location("fl_server", ROOT / "app" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def client(tmp_path):
    server = _load_server()
    # 数据目录里放一份"10-K"和一份 XBRL，文件名按 fetch_edgar.py 的约定拼
    (tmp_path / "0000000042_10k_2026-09-30.htm").write_text(fixtures.FAKE_10K_HTML)
    (tmp_path / "0000000042_facts.json").write_text(json.dumps(fixtures.FAKE_FACTS))
    server.configure(tmp_path)
    return TestClient(server.app)


def test_lists_available_filings(client):
    body = client.get("/api/filings").json()
    assert len(body["filings"]) == 1
    assert body["filings"][0]["cik"] == "0000000042"
    assert body["filings"][0]["period"] == "2026-09-30"
    assert body["filings"][0]["has_xbrl"] is True


def test_meta_counts_sections_and_chunks(client):
    m = client.get("/api/meta", params={"cik": "0000000042"}).json()
    assert m["sections"] >= 2          # 夹具至少有 Item 1 与 Item 7
    assert m["chunks"] > 0
    assert m["has_xbrl"] is True


def test_numeric_question_uses_xbrl_and_cites_it(client):
    r = client.get("/api/ask", params={"cik": "0000000042", "q": "营收多少？"}).json()
    assert r["status"] == "ok"
    assert r["kind"] == "metric"
    assert "175.0M" in r["text"]
    assert r["citations"] and r["citations"][0]["kind"] == "xbrl"
    assert r["citations"][0]["ref"]  # 出处非空


def test_text_question_points_at_a_specific_item(client):
    r = client.get("/api/ask", params={"cik": "0000000042", "q": "供应链集中在哪些地区？"}).json()
    assert r["status"] == "ok"
    assert r["kind"] == "excerpt"
    assert r["citations"][0]["ref"].startswith("0000000042_10k_2026-09-30#Item")


def test_off_topic_question_refuses_without_citations(client):
    r = client.get("/api/ask", params={"cik": "0000000042", "q": "CEO 的生日是哪天？"}).json()
    assert r["status"] == "insufficient_evidence"
    assert r["citations"] == []


def test_unknown_cik_says_what_to_run(client):
    resp = client.get("/api/ask", params={"cik": "0000009999", "q": "营收多少？"})
    assert resp.status_code == 404
    assert "fetch_edgar" in resp.json()["detail"]


def test_page_renders(client):
    html = client.get("/").text
    assert "filing" in html and "/api/ask" in html
