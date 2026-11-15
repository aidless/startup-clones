"""docs/REVIEW-R3-filing-geo.md 里 filing-lens 侧的发现，逐条复现（先红后绿）。

每条都对应报告里的一个编号；断言里的字符串是从真实命令输出里逐字抄来的，
不是照报告转述重写的——报告转述过的地方以真跑为准。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from filinglens import corpus, edgar, facts as F, fixtures
from filinglens.answer import Answerer, headcount_number

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _real(tag: str):
    """加载 data/ 里的真实申报；文件不在就跳过（测试不联网）。

    `data/` 是被 .gitignore 掉的 164MB SEC 语料，别人的干净检出里没有它；
    补齐命令写进 skip reason，别让后来人猜。
    """
    if not (DATA / f"{tag}_facts.json").exists() or not list(DATA.glob(f"{tag}_10k_*.htm")):
        pytest.skip(
            f"data/ 里没有 {tag} 的真实申报；"
            "先跑 `cd filing-lens && python3 scripts/batch_bench.py` 抓回 22 份 10-K"
            "（只用本地已有文件：python3 scripts/batch_bench.py --no-fetch）")
    return corpus.load(str(DATA), tag)


def _small(html: str, conn: sqlite3.Connection | None = None) -> Answerer:
    _, chunks, _ = edgar.parse(html, doc="T")
    return Answerer(chunks, conn)


def _body_numbers(text: str) -> list[str]:
    """正文里的「量」——年份不算，与 answer.has_quantity 同一口径。"""
    out = []
    for raw in re.findall(r"\d[\d,.]*", text):
        if re.fullmatch(r"(19|20)\d{2}", raw.strip(".,")):
            continue
        out.append(raw)
    return out


# ---------------------------------------------------------------- P0-1 员工数「明确拒答」是假的

def test_intel_headcount_is_found_despite_footnote_marker():
    """真实命令复现：Intel 10-K 正文写 `comprised of 85,100` + 独立一行脚注 `1` + `people`。

    旧实现把脚注的 `1` 也当成正文，`HEADCOUNT_RE` 于是匹配到 `1 people`，
    全文扫句判定「没有 N 名员工」→ 拒答，拒答文案还断言文件里没有这句话（假话）。
    """
    f = _real("0000050863")
    r = f.answerer.ask("有多少员工？")
    assert r.status == "ok", f"Intel 的员工数没答出来：{r.text}"
    assert "85,100" in r.text


def test_qualcomm_temporary_workers_are_counted():
    """真实句子：`we had approxima tely 57,000 full-time, part-time and temporary workers`。

    旧 `HEADCOUNT_RE` 只认 employees/people/associates…，不认 workers，全句无匹配。
    """
    f = _real("0000804328")
    r = f.answerer.ask("有多少员工？")
    assert r.status == "ok", f"Qualcomm 的员工数没答出来：{r.text}"
    assert "57,000" in r.text


def test_isolated_footnote_line_does_not_fake_a_headcount():
    """正对照的反面：脚注那行不能被读成人数（`1 people` 是旧实现的错误匹配）。"""
    html = (
        "<html><body><p>Item 1. Business</p>"
        "<p>We invest in our highly skilled workforce, which was comprised of 85,100</p>"
        "<p>1</p>"
        "<p>people as of December 27, 2025, by creating practices and programs.</p>"
        "</body></html>"
    )
    text = edgar.html_to_text(html)
    assert headcount_number(text) is not None
    assert not headcount_number(text).startswith("1 "), \
        f"脚注被当成人数了：{headcount_number(text)!r}"
    assert "85,100" in headcount_number(text)


def test_headcount_refusal_does_not_claim_the_document_lacks_it():
    """拒答可以说「没匹配到句式」，不能说「全文没有这句陈述」——那是关于文件的事实主张。"""
    a = _small(
        "<html><body><p>Item 1. Business</p>"
        "<p>The Company designs lidar sensors for industrial robots and sells them "
        "worldwide to automation vendors and integrators.</p></body></html>"
    )
    r = a.ask("有多少员工？")
    assert r.status == "insufficient_evidence"
    assert "全文没有" not in r.text, f"拒答在替文件下结论：{r.text}"
    assert "未匹配到" in r.text


# ---------------------------------------------------------------- P0-2 metric 取到季度值

def test_annual_series_skips_quarterly_rows_tucked_into_10k():
    """SEC companyfacts 把 10-K 里的季度值也标成 fp='FY'，只能靠时长区分。"""
    rows = [
        {"fy": 2019, "fp": "FY", "start": "2018-09-30", "end": "2019-09-28",
         "val": 260174000000, "form": "10-K", "filed": "2019-10-31", "frame": None},
        {"fy": 2020, "fp": "FY", "start": "2019-06-30", "end": "2019-09-28",
         "val": 64040000000, "form": "10-K", "filed": "2020-10-30", "frame": "CY2019Q3"},
        {"fy": 2020, "fp": "FY", "start": "2019-09-29", "end": "2020-09-26",
         "val": 274515000000, "form": "10-K", "filed": "2020-10-30", "frame": None},
    ]
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    conn = F.load_companyfacts(payload, ":memory:")
    series = F.annual_series(conn, "revenue")
    assert [(f.fy, f.val) for f in series] == [(2019, 260174000000), (2020, 274515000000)]


def test_apple_revenue_series_is_annual_only():
    f = _real("0000320193")
    series = F.annual_series(f.conn, "revenue")
    vals = {s.fy: s.val for s in series}
    # 报告里点名的两行：旧实现给的是 64.04B / 64.70B（季度值）
    assert vals[2019] == 260174000000, f"FY2019 = {vals.get(2019)}"
    assert vals[2020] == 274515000000, f"FY2020 = {vals.get(2020)}"
    assert vals[2026] == 478834000000
    fys = [s.fy for s in series]
    assert fys == sorted(set(fys)), f"同一个财年出现多次：{fys}"


def test_metric_command_shows_no_annual_from_quarter_mixup(capsys):
    """真实命令：`metric revenue` 曾印出 FY2019 64.04B / FY2020 64.70B / YoY +465.4%。"""
    _real("0000320193")            # 没有 data/ 就跳过，并给出抓取命令
    from filinglens import cli
    rc = cli.main(["metric", "revenue", "--facts",
                   str(DATA / "0000320193_facts.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "FY2019  260.17B" in out and "FY2020  274.51B" in out, out
    assert "+465.4%" not in out
    assert "FY2026  478.83B" in out                   # 正对照：最新一年不变


# ---------------------------------------------------------------- P0-3 无 XBRL 披露却答离题段

def test_missing_xbrl_metric_refuses_instead_of_citing_offtopic_text():
    """Amazon 的 XBRL 没有 R&D 标签，英文路径说 no_data；中文提问却被 IPR&D 会计政策段顶上。"""
    f = _real("0001018724")
    r = f.answerer.ask("研发费用是多少？")
    assert r.status in ("no_data", "insufficient_evidence"), f"拿离题段落冒充答案：{r.text}"
    assert r.citations == [], f"没有 XBRL 数据却给了引用：{r.citations}"
    assert "XBRL" in r.text


def test_positive_control_disclosed_metric_still_answers():
    f = _real("0001018724")
    r = f.answerer.ask("营收是多少？")
    assert r.status == "ok" and r.kind == "metric"
    assert all(c.kind == "xbrl" for c in r.citations)


# ---------------------------------------------------------------- P1-2 文本通道出数字

def test_text_excerpt_with_body_numbers_is_labelled_not_passed_as_xbrl():
    """摘录里可以有正文数字（48%），但必须标注来源，不能让人以为出自 XBRL。"""
    _, chunks, _ = edgar.parse(fixtures.FAKE_10K_HTML, doc="ACME")
    conn = F.load_companyfacts(fixtures.FAKE_FACTS, ":memory:")
    r = Answerer(chunks, conn).ask("top customers concentration revenue")
    assert r.status == "ok" and r.kind == "excerpt"
    assert _body_numbers(r.text), "这条摘录本来就带正文数字"
    assert "XBRL" in r.note, f"正文数字没标来源：{r.note!r}"


def test_clean_excerpt_has_no_source_note():
    """正对照：不含量的摘录不需要那条注。"""
    a = _small(
        "<html><body><p>Item 1a. Risk Factors</p>"
        "<p>Supply chain concentration is a risk: the lidar module comes from one "
        "supplier and qualification takes several quarters.</p></body></html>"
    )
    r = a.ask("supply chain concentration risk lidar supplier")
    assert r.status == "ok" and r.kind == "excerpt"
    assert r.note == ""


def test_numeric_question_is_not_answered_from_body_text():
    """问「多少」时，正文摘录不能代答——数字只走 XBRL。"""
    a = _small(
        "<html><body><p>Item 1a. Risk Factors</p>"
        "<p>We depend on a limited number of large customers. Our top five customers "
        "accounted for 48% of revenue in fiscal 2025.</p></body></html>"
    )
    r = a.ask("前五大客户占了收入多少？")
    assert r.status == "insufficient_evidence", f"正文数字冒充了 XBRL：{r.text}"
    assert r.citations == []


# ---------------------------------------------------------------- P1-3 概念覆盖率口径

def test_readme_coverage_rule_matches_implementation():
    """README 写「至少一半出现」，代码是「命中一个就够」，且代码里带实测反证。

    以代码为准（注释记录了「过半」把 9/20 家员工数提问判成证据不足），
    所以修的是 README 那句与实现相反的话。
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "至少一半出现" not in readme, "README 仍写着与实现相反的覆盖率口径"


# ---------------------------------------------------------------- P2-1 / P2-5 README 漂移

def test_readme_demo_block_lists_every_sample_question():
    from filinglens import cli
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [q for q in cli.SAMPLE_QUESTIONS if q not in readme]
    assert missing == [], f"README 的演示块漏了 {missing}"


def test_readme_port_matches_server_default():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    m = re.search(r"--port[\"'],?\s*type=int,\s*default=(\d+)", server)
    assert m, "app/server.py 里找不到 --port 的默认值"
    default = m.group(1)
    assert f"--port {default}" in readme, f"README 里的 --port 与默认值 {default} 不一致"


def test_readme_demo_block_matches_real_output(capsys):
    """README 的演示块必须能被实跑输出逐行命中（P2-1 的根因是块是手抄的）。"""
    from pathlib import Path

    from filinglens import cli

    cli.main(["demo"])
    out = capsys.readouterr().out
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    block = readme.split("## 演示输出（真实运行结果）")[1].split("```")[1]
    missing = [l for l in block.splitlines() if l.strip() and l.strip() not in out]
    assert not missing, f"README 演示块有 {len(missing)} 行与实跑不符：{missing}"
