"""他山之石第二轮：错误响应按 RFC 9457 `application/problem+json` 的形状给。

来源 https://www.rfc-editor.org/rfc/rfc9457 ：错误体的五个成员
`type` / `title` / `status` / `detail` / `instance`，媒体类型固定
`application/problem+json`。ID 草案 draft-ietf-httpapi-idempotency-key-header-08 §2.7
也是这个形状（缺键 400 / 复用 422 / 处理中 409）。

现状（会红）：`/api/filing` 的坏 CIK 走 FastAPI 默认的 `{"detail": …}`，
`q` 太短走默认的 422 `{"detail": [{...}]}`，两者都不是 problem+json。

注意正对照：「data/ 下没有这份 10-K」是**正常状态**（面板要就地解释），
仍然是 200 + `status="no_data"`，不能因为借了 problem+json 就把它改成错误。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as console_app

# 面板读的是 filing-lens 的真实语料（22 份 10-K，164MB，.gitignore 掉的）。
FILING_DATA = Path(__file__).resolve().parents[2] / "filing-lens" / "data"


def _needs_filing() -> None:
    """「正常回答」这条要真实 Apple 申报；干净检出里没有 data/ → 跳过（其余照跑）。

    补齐：
        cd filing-lens && python3 scripts/batch_bench.py
    （只用本地已经抓下来的文件时加 `--no-fetch`）
    """
    if not (FILING_DATA / "0000320193_facts.json").exists() \
            or not list(FILING_DATA.glob("0000320193_10k_*.htm")):
        pytest.skip(
            f"缺少 {FILING_DATA}/0000320193_10k_*.htm 与 0000320193_facts.json；"
            "先跑 `cd filing-lens && python3 scripts/batch_bench.py` 抓回 22 份 10-K"
            "（只用本地已有文件：python3 scripts/batch_bench.py --no-fetch）")


@pytest.fixture(scope="module")
def client():
    return TestClient(console_app.app)


def _problem(resp) -> dict:
    assert resp.headers["content-type"].startswith("application/problem+json"), \
        resp.headers["content-type"]
    body = json.loads(resp.content)
    assert {"type", "title", "status", "detail"} <= set(body), body
    assert isinstance(body["status"], int) and body["status"] == resp.status_code, body
    return body


def test_bad_cik_is_a_problem_document(client):
    resp = client.get("/api/filing", params={"cik": "not-a-cik"})
    assert resp.status_code == 400
    body = _problem(resp)
    assert "cik" in body["detail"].lower() or "cik" in json.dumps(body).lower()


def test_validation_error_is_a_problem_document_with_errors_extension(client):
    resp = client.get("/api/filing", params={"q": "x"})     # min_length=2 → 422
    assert resp.status_code == 422
    body = _problem(resp)
    assert "errors" in body and body["errors"], body


def test_missing_local_10k_stays_a_normal_state(client):
    """正对照：没下载文件不是错误，面板要就地显示提示。"""
    resp = client.get("/api/filing", params={"cik": "0000000001"})
    assert resp.status_code == 200
    assert json.loads(resp.content)["status"] == "no_data"


def test_happy_path_is_untouched(client):
    """正对照：正常回答仍是普通 JSON，不带 problem 成员。"""
    _needs_filing()
    resp = client.get("/api/filing", params={"cik": "0000320193", "q": "营收多少"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = json.loads(resp.content)
    assert "chunks" in body and "citations" in body
    assert "type" not in body
