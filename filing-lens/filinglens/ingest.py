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
import logging
import os
import re
import time
import zlib
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_UA = "filing-lens-research/0.1 (contact: research@example.com)"
# SEC 的公平访问政策要求 User-Agent 里带真实联系方式，换人用就得换成自己的。
UA = os.environ.get("SEC_UA") or DEFAULT_UA
ALLOWED_HOSTS = {"www.sec.gov", "sec.gov", "data.sec.gov"}
MAX_BYTES = 40 * 1024 * 1024
DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"

logger = logging.getLogger(__name__)


# 落盘名的唯一合法形状：单段、字母数字开头、无路径分隔符、无 glob 元字符。
# tag 与 period 会拼进 `{tag}_10k_{period}.htm`，而 corpus/discover 又用 "_" 反解文件名，
# 所以连下划线也不许出现 —— 否则 tag="a_b" 会让反查拿到 "a"。
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}")
_CIK_IN_ARCHIVE_PATH = re.compile(r"/data/(\d{1,10})/")
_CIK_IN_FACTS_URL = re.compile(r"CIK(\d{1,10})\.json")


def safe_component(value: str, kind: str) -> str:
    """把用户给的名字收成一个可安全拼路径的单段。

    不「清洗」成合法值 —— 直接拒绝。清洗会让 `../../escaped` 悄悄变成 `escaped`
    写进 data/，调用方以为写到了别处；报错才能让人知道自己给错了。
    """
    raw = "" if value is None else str(value)
    if not raw  or not _SAFE_COMPONENT.fullmatch(raw) or raw in (".", ".."):
        raise IngestError(f"{kind} 只能是字母数字与 . - 组成的单段（≤64，不能带 / \\ * ? _），"
                          f"收到 {raw!r}")
    return raw


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
    return _gunzip_limited(raw) if gz else raw


def _gunzip_limited(raw: bytes, limit: int | None = None) -> bytes:
    """边解边限量。原实现先 `gzip.decompress` 再判大小：199KB 的炸弹能解出 200MB，
    上限形同虚设（压缩前字节数完全不反映解压后的大小）。"""
    limit = MAX_BYTES if limit is None else limit
    obj = zlib.decompressobj(16 + zlib.MAX_WBITS)      # 16+ = gzip 容器
    try:
        out = obj.decompress(raw, limit + 1)           # 只多要 1 字节，够判超限
    except zlib.error as exc:
        raise IngestError(f"gzip 解压失败：{exc}") from exc
    if len(out) > limit:
        raise IngestError(f"解压后超过上限 {limit // 1024 // 1024}MB，拒绝落盘")
    return out


def _tenks(cik10: str) -> list[dict]:
    """submissions 里全部 10-K（新到旧），一条一份。"""
    payload = json.loads(download(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    recent = payload["filings"]["recent"]
    out = []
    for form, acc, doc, filed, period in zip(recent["form"], recent["accessionNumber"],
                                             recent["primaryDocument"], recent["filingDate"],
                                             recent["reportDate"]):
        if form != "10-K":
            continue
        accn = acc.replace("-", "")
        out.append({
            "cik": cik10,
            "company": payload.get("name", ""),
            "accession": acc,
            "filed": filed,
            "period": period or filed,
            "html_url": (f"https://www.sec.gov/Archives/edgar/data/"
                         f"{int(cik10)}/{accn}/{doc}"),
            "facts_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
        })
    return out


def latest_10k(cik: str) -> dict:
    """从 submissions 里取最近一份 10-K 的下载信息。"""
    cik10 = normalize_cik(cik)
    found = _tenks(cik10)
    if not found:
        raise IngestError(f"CIK {cik10} 最近的申报里没有 10-K")
    return found[0]


def prior_10k(cik: str, before_period: str) -> dict:
    """同一 CIK 里 reportDate 早于 before_period 的最近一份 10-K。

    风险因素年度差异要靠它：只有一份 10-K 时那一项只能写「无法比较」，
    等于把「没测」当成「没问题」。
    """
    cik10 = normalize_cik(cik)
    found = [k for k in _tenks(cik10) if (k["period"] or k["filed"]) < before_period]
    if not found:
        raise IngestError(f"CIK {cik10} 在 {before_period} 之前没有更早的 10-K")
    return found[0]


def _write(html: bytes, facts_payload: dict | None, tag: str, period: str,
           data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    tag = safe_component(tag, "tag")
    period = safe_component(period, "period")
    data_dir.mkdir(parents=True, exist_ok=True)
    html_path = data_dir / f"{tag}_10k_{period}.htm"
    # 第二道防线：即便上面的正则被改坏，也不许写到 data/ 之外
    if html_path.resolve().parent != data_dir.resolve():
        raise IngestError(f"落盘路径越出数据目录：{html_path}")
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


def from_cik(cik: str, data_dir: str | Path = DEFAULT_DATA, pause: float = 1.2,
             period: str | None = None, prior_to: str | None = None) -> dict:
    """按 CIK 抓一份 10-K 与 companyfacts。

    `period` 指定要哪一期；`prior_to` 表示「早于这一期的那一份」（年度 diff 用）。
    两个都不给就是最近一份。
    """
    data_dir = Path(data_dir)
    if prior_to:
        info = prior_10k(cik, prior_to)
    elif period:
        cands = [k for k in _tenks(normalize_cik(cik)) if k["period"] == period]
        if not cands:
            raise IngestError(f"CIK {normalize_cik(cik)} 没有 reportDate={period} 的 10-K")
        info = cands[0]
    else:
        info = latest_10k(cik)
    html = download(info["html_url"])
    time.sleep(pause)          # SEC 要求 <=10 req/s，这里更保守
    facts_payload = None
    try:
        facts_payload = json.loads(download(info["facts_url"]))
    except (OSError, ValueError) as exc:
        # 没有 XBRL 也要能用文本路径，所以这里不中断抓取。但必须说清楚「退化成了什么」：
        # 之前这里是一句裸 except，下载失败、JSON 损坏、超限全都静默，调用方拿到
        # 一份 has_xbrl=false 的结果却不知道为什么，只能去猜。
        # OSError = 网络/URL 错误（URLError/HTTPError/超时），ValueError = JSON 解析失败
        # 或 IngestError（大小超限、gzip 解压失败）。
        logger.warning("XBRL 事实没拿到（CIK %s）：%s；本次只建文本索引，数字类问题会答 no_data。",
                       info["cik"], exc)
        facts_payload = None
    out = _write(html, facts_payload, info["cik"], info["period"], data_dir)
    out.update({"company": info["company"], "filed": info["filed"], "cik": info["cik"],
                "accession": info.get("accession", "")})
    return out


_FORM_10K_RE = re.compile(r"\b10-K\b", re.I)


def looks_like_10k(html: bytes) -> bool:
    """下载物到底是不是一份 10-K。

    只认「正文里出现 10-K 这个表种」——不追求精确识别（那要整份解析），
    但要挡住把首页、404 页、登录页当 10-K 存进库：这类页面存进去后
    `corpus` 会解析出零个 Item、答案器全部拒答，用户以为抓取成功了。
    """
    head = html[: 512 * 1024].decode("utf-8", errors="ignore")
    return bool(_FORM_10K_RE.search(head))


def _cik_from(url: str, pattern: re.Pattern[str]) -> str | None:
    m = pattern.search(url)
    return normalize_cik(m.group(1)) if m else None


def from_url(url: str, data_dir: str | Path = DEFAULT_DATA,
             facts_url: str | None = None, tag: str | None = None,
             period: str | None = None) -> dict:
    """把一个 10-K 的 URL 丢进去。tag 决定落盘名，缺省用 URL 摘要。

    tag 用 URL 摘要而不是公司名：同一家公司可能有多份 10-K（不同财年），
    用公司名会互相覆盖；用 URL 摘要则天然唯一，且能反查"这是从哪来的"。
    """
    data_dir = Path(data_dir)
    html = download(url)
    if not looks_like_10k(html):
        raise IngestError(f"下载内容不像 10-K（正文没有出现 10-K 表种）：{url}")
    facts_payload = json.loads(download(facts_url)) if facts_url else None
    tag = tag or "url" + hashlib.sha1(url.encode()).hexdigest()[:8]
    period = period or time.strftime("%Y-%m-%d")
    tag = safe_component(tag, "tag")
    period = safe_component(period, "period")

    # CIK 三方对齐：归档路径里的 CIK、facts_url 里的 CIK、调用方给的 tag。
    # 不对齐 = 数字来自 A 公司、正文来自 B 公司，答案会把两家的数拼在一起。
    src_cik = _cik_from(url, _CIK_IN_ARCHIVE_PATH)
    facts_cik = _cik_from(facts_url, _CIK_IN_FACTS_URL) if facts_url else None
    if src_cik and facts_cik and src_cik != facts_cik:
        raise IngestError(f"facts_url 的 CIK({facts_cik}) 与归档路径的 CIK({src_cik}) 不一致")
    expect = src_cik or facts_cik
    if expect and tag.isdigit() and len(tag) <= 10 and normalize_cik(tag) != expect:
        raise IngestError(f"tag({tag}) 与来源 CIK({expect}) 不一致")
    out = _write(html, facts_payload, tag, period, data_dir)
    out.update({"source_url": url, "tag": tag})
    return out
