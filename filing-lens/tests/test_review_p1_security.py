"""审查报告 P1（filing-lens 安全面）四条的复现测试（2026-11-12 审查）。

1. tag / period 直接拼进落盘路径：`tag="../../escaped"` 写到 data 目录外，
   绝对路径任意落盘，`tag=0000320193 + period=2026-09-26` 覆盖真实 10-K。
2. 大小上限只数「压缩前」字节：199KB 的 gzip 解出 200MB，MAX_BYTES=40MB 被绕。
3. tag 当 glob 用：`corpus.load('data','*')` 返回别家，`GET /api/meta?cik=*` 以 200 返回任意文件。
4. 不校验下载物是不是 10-K，也不比对 tag / facts_url 的 CIK —— 把任意页面当 10-K 存进库。
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filinglens import corpus, fixtures, ingest  # noqa: E402


def _stub_download(mapping: dict[str, bytes], monkeypatch):
    calls = []

    def fake(url, timeout=90.0):
        calls.append(url)
        for key, payload in mapping.items():
            if key in url:
                return payload
        raise AssertionError(f"测试没准备这个 URL 的响应: {url}")

    monkeypatch.setattr(ingest, "download", fake)
    return calls


def _facts_url(cik: str) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


# ---------------- P1-1 落盘名必须是干净的单段 ----------------

@pytest.mark.parametrize("tag", ["../../escaped", "/tmp/abs", "a/b", "..", "x" * 200,
                                 "na*me", "a b", "a_b"])
def test_from_url_rejects_unsafe_tag(tag, tmp_path, monkeypatch):
    _stub_download({"10-k.htm": fixtures.FAKE_10K_HTML.encode()}, monkeypatch)
    with pytest.raises(ingest.IngestError):
        ingest.from_url("https://www.sec.gov/Archives/10-k.htm", tmp_path, tag=tag)


@pytest.mark.parametrize("period", ["../../2026", "2026/09/30", "/abs", "x" * 80])
def test_from_url_rejects_unsafe_period(period, tmp_path, monkeypatch):
    _stub_download({"10-k.htm": fixtures.FAKE_10K_HTML.encode()}, monkeypatch)
    with pytest.raises(ingest.IngestError):
        ingest.from_url("https://www.sec.gov/Archives/10-k.htm", tmp_path, period=period)


def test_unsafe_tag_writes_nothing_outside_data_dir(tmp_path, monkeypatch):
    _stub_download({"10-k.htm": fixtures.FAKE_10K_HTML.encode()}, monkeypatch)
    data = tmp_path / "data"
    with pytest.raises(ingest.IngestError):
        ingest.from_url("https://www.sec.gov/Archives/10-k.htm", data, tag="../../escaped")
    assert not (tmp_path / "escaped_10k_2026-09-30.htm").exists()
    assert not any(data.glob("*")) if data.exists() else True


def test_safe_tag_still_works(tmp_path, monkeypatch):
    # 正对照：正常 tag / period 照旧落盘
    _stub_download({"10-k.htm": fixtures.FAKE_10K_HTML.encode()}, monkeypatch)
    out = ingest.from_url("https://www.sec.gov/Archives/10-k.htm", tmp_path,
                          tag="0000320193", period="2026-09-26")
    assert Path(out["html"]).name == "0000320193_10k_2026-09-26.htm"
    assert Path(out["html"]).exists()


# ---------------- P1-2 gzip 炸弹 ----------------

class _FakeResp:
    """假的 urlopen 响应：只实现 download() 用到的三样东西。"""

    def __init__(self, payload: bytes, gz: bool):
        self._buf = payload
        self._pos = 0
        self.headers = {"Content-Encoding": "gzip"} if gz else {}

    def read(self, n: int) -> bytes:
        piece = self._buf[self._pos:self._pos + n]
        self._pos += len(piece)
        return piece

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(payload: bytes, gz: bool, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload, gz))


def test_gzip_bomb_rejected_by_download(monkeypatch):
    """走真实的 download() 分支：Content-Encoding=gzip 时先解压再判大小。"""
    monkeypatch.setattr(ingest, "MAX_BYTES", 1 << 20)          # 1MB，测试要快
    bomb = gzip.compress(b"\0" * (5 << 20))                    # 5MB 全零，压完 ~5KB
    _serve(bomb, True, monkeypatch)
    with pytest.raises(ingest.IngestError):
        ingest.download("https://www.sec.gov/Archives/10-k.htm")


def test_gzip_within_limit_still_ok(monkeypatch):
    # 正对照：正常 gzip 内容仍能解开
    monkeypatch.setattr(ingest, "MAX_BYTES", 1 << 20)
    body = fixtures.FAKE_10K_HTML.encode()
    _serve(gzip.compress(body), True, monkeypatch)
    assert ingest.download("https://www.sec.gov/Archives/10-k.htm") == body


def test_gunzip_limited_is_the_guard():
    # 直接对守卫下断言：不是只靠 gzip.decompress 的自由行为
    with pytest.raises(ingest.IngestError):
        ingest._gunzip_limited(gzip.compress(b"\0" * (2 << 20)), limit=1 << 20)


# ---------------- P1-3 tag 不能当 glob ----------------

def _write_filing(d: Path, tag: str, period: str = "2026-09-30"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tag}_10k_{period}.htm").write_text(fixtures.FAKE_10K_HTML)
    (d / f"{tag}_facts.json").write_text(json.dumps(fixtures.FAKE_FACTS))


def test_corpus_load_rejects_glob_tag(tmp_path):
    _write_filing(tmp_path, "0000000042")
    for bad in ("*", "00000000*", "?", "[0-9]*"):
        with pytest.raises((FileNotFoundError, ValueError)):
            corpus.load(tmp_path, bad)


def test_corpus_load_exact_tag(tmp_path):
    _write_filing(tmp_path, "0000000042")
    _write_filing(tmp_path, "0000999999")
    f = corpus.load(tmp_path, "0000000042")
    assert f.cik == "0000000042", "glob 语义把别家返回来了"


# ---------------- P1-4 下载物必须是 10-K，且 CIK 要对得上 ----------------

def test_non_10k_page_rejected(tmp_path, monkeypatch):
    _stub_download({"not-a-filing.htm": b"<html><body>Welcome to our homepage</body></html>"},
                   monkeypatch)
    with pytest.raises(ingest.IngestError):
        ingest.from_url("https://www.sec.gov/Archives/not-a-filing.htm", tmp_path, tag="x1")


def test_facts_cik_must_match_source(tmp_path, monkeypatch):
    """facts_url 指向别家 CIK：数字与正文来自两家公司，答案会张冠李戴。"""
    _stub_download({
        "edgar/data/320193/": fixtures.FAKE_10K_HTML.encode(),
        "CIK0000000042.json": json.dumps(fixtures.FAKE_FACTS).encode(),
    }, monkeypatch)
    with pytest.raises(ingest.IngestError):
        ingest.from_url("https://www.sec.gov/Archives/edgar/data/320193/10-k.htm", tmp_path,
                        facts_url=_facts_url("0000000042"), tag="0000320193")


def test_facts_cik_match_ok(tmp_path, monkeypatch):
    # 正对照：CIK 一致时正常写入
    _stub_download({
        "edgar/data/42/": fixtures.FAKE_10K_HTML.encode(),
        "CIK0000000042.json": json.dumps(fixtures.FAKE_FACTS).encode(),
    }, monkeypatch)
    out = ingest.from_url("https://www.sec.gov/Archives/edgar/data/42/10-k.htm", tmp_path,
                          facts_url=_facts_url("0000000042"), tag="0000000042",
                          period="2026-09-30")
    assert Path(out["html"]).exists() and out["facts"]


# ---------------- P1-5 写入接口要有凭据 ----------------

def _load_server():
    spec = importlib.util.spec_from_file_location("fl_server_sec", ROOT / "app" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ingest_endpoint_requires_token(tmp_path, monkeypatch):
    server = _load_server()
    _write_filing(tmp_path, "0000000042")
    server.configure(tmp_path)
    monkeypatch.setattr(server, "INGEST_TOKEN", "s3cret")
    c = TestClient(server.app)
    r = c.post("/api/ingest", json={"cik": "320193"})
    assert r.status_code == 403
    r2 = c.post("/api/ingest", json={"cik": "320193"}, headers={"X-Ingest-Token": "wrong"})
    assert r2.status_code == 403


def test_ingest_endpoint_closed_when_token_unset(tmp_path, monkeypatch):
    # fail-closed：没配 token = 接口关闭，不是「谁都能写」
    server = _load_server()
    _write_filing(tmp_path, "0000000042")
    server.configure(tmp_path)
    monkeypatch.setattr(server, "INGEST_TOKEN", "")
    c = TestClient(server.app)
    assert c.post("/api/ingest", json={"cik": "320193"}).status_code == 403


def test_meta_rejects_glob_cik(tmp_path):
    server = _load_server()
    _write_filing(tmp_path, "0000000042")
    server.configure(tmp_path)
    c = TestClient(server.app)
    r = c.get("/api/meta", params={"cik": "*"})
    assert r.status_code in (400, 404), f"通配符把任意文件以 {r.status_code} 返回了"
