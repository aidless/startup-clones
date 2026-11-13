"""把一个 10-K 弄进 data/ —— 从 CIK 或从一个 URL。

为什么单独一层：demo 服务、批量基准脚本、命令行都要"拿到一份能解析的文件"，
如果三处各写一遍下载逻辑，就会出现三种不同的 User-Agent、三种不同的限速策略、
以及三种不同的"这个 URL 到底能不能抓"的判断。这里只写一次。

三条纪律：
1. 只抓 HTTPS 且 host 在 `ALLOWED_HOSTS` 里（SEC 域名 + 本地就是全部合法来源）。
2. 单文件上限 `MAX_BYTES`，边读边数，超了立刻停——不要先下完再判。
3. 落盘的文件名必须让 `app/server.py` 能按 CIK 找回来：`{tag}_10k_{period}.htm`
   与 `{tag}_facts.json` 必须同一个 tag。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "filing-lens-research/0.1 (contact: research@example.com)"
ALLOWED_HOSTS = {"www.sec.gov", "sec.gov", "data.sec.gov"}
MAX_BYTES = 40 * 1024 * 1024
DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


class IngestError(ValueError):
    """输入不合法或下载失败。带上人话，直接能显示给用户。"""


def normalize_cik(cik: str | int) -> str:
    """'320193' / '0000320193' / 'CIK320193' → '0000320193'。"""
    raw = str(cik).strip().upper().removeprefix("CIK").strip()
    if not raw.isdigit():
        raise IngestError(f"CIK 必须是数字，收到 {cik!r}")
    if len(raw) > 10:
        raise IngestError(f"CIK 超过 10 位：{cik!r}")
    return f"{int(raw):010d}"


def _check_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise IngestError(f"只接受 https，收到 {parsed.scheme or '(空)'}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise IngestError(f"只接受 SEC 域名 {sorted(ALLOWED_HOSTS)}，收到 {parsed.hostname!r}")
    return url


def download(url: str, timeout: float = 90.0) -> bytes:
    """带大小上限的下载。超限立刻抛，不把 40MB 全读进内存再判。"""
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        gz = resp.headers.get("Content-Encoding") == "gzip"
        buf, total = bytearray(), 0
        while True:
            piece = resp.read(1 << 16)
            if not piece:
                break
            total += len(piece)
            if total > MAX_BYTES:
                raise IngestError(f"文件超过上限 {MAX_BYTES // 1024 // 1024}MB：{url}")
            buf += piece
        raw = bytes(buf)
    return gzip.decompress(raw) if gz else raw


def latest_10k(cik: str) -> dict:
    """从 submissions 里取最近一份 10-K 的下载信息。"""
    cik10 = normalize_cik(cik)
    payload = json.loads(download(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    recent = payload["filings"]["recent"]
    for form, acc, doc, filed, period in zip(recent["form"], recent["accessionNumber"],
                                             recent["primaryDocument"], recent["filingDate"],
                                             recent["reportDate"]):
        if form == "10-K":
            accn = acc.replace("-", "")
            return {
                "cik": cik10,
                "company": payload.get("name", ""),
                "accession": acc,
                "filed": filed,
                "period": period or filed,
                "html_url": (f"https://www.sec.gov/Archives/edgar/data/"
                             f"{int(cik10)}/{accn}/{doc}"),
                "facts_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
            }
    raise IngestError(f"CIK {cik10} 最近的申报里没有 10-K")


def _write(html: bytes, facts_payload: dict | None, tag: str, period: str,
           data_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    html_path = data_dir / f"{tag}_10k_{period}.htm"
    html_path.write_bytes(html)
    facts_path = None
    if facts_payload is not None:
        facts_path = data_dir / f"{tag}_facts.json"
        facts_path.write_text(json.dumps(facts_payload))
    return {
        "tag": tag,
        "period": period,
        "html": str(html_path),
        "facts": str(facts_path) if facts_path else None,
        "html_kb": round(len(html) / 1024),
        "facts_kb": round(len(json.dumps(facts_payload)) / 1024) if facts_payload else 0,
    }


def from_cik(cik: str, data_dir: str | Path = DEFAULT_DATA, pause: float = 1.2) -> dict:
    """按 CIK 抓最近一份 10-K 与 companyfacts。"""
    data_dir = Path(data_dir)
    info = latest_10k(cik)
    html = download(info["html_url"])
    time.sleep(pause)          # SEC 要求 <=10 req/s，这里更保守
    facts_payload = None
    try:
        facts_payload = json.loads(download(info["facts_url"]))
    except Exception:          # noqa: BLE001 —— 没有 XBRL 也要能用文本路径
        facts_payload = None
    out = _write(html, facts_payload, info["cik"], info["period"], data_dir)
    out.update({"company": info["company"], "filed": info["filed"], "cik": info["cik"]})
    return out


def from_url(url: str, data_dir: str | Path = DEFAULT_DATA,
             facts_url: str | None = None, tag: str | None = None,
             period: str | None = None) -> dict:
    """把一个 10-K 的 URL 丢进去。tag 决定落盘名，缺省用 URL 摘要。

    tag 用 URL 摘要而不是公司名：同一家公司可能有多份 10-K（不同财年），
    用公司名会互相覆盖；用 URL 摘要则天然唯一，且能反查"这是从哪来的"。
    """
    data_dir = Path(data_dir)
    html = download(url)
    facts_payload = json.loads(download(facts_url)) if facts_url else None
    tag = tag or "url" + hashlib.sha1(url.encode()).hexdigest()[:8]
    period = period or time.strftime("%Y-%m-%d")
    out = _write(html, facts_payload, tag, period, data_dir)
    out.update({"source_url": url, "tag": tag})
    return out
