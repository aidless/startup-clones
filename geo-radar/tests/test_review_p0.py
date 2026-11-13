"""审查报告 P0-12 + geo-radar 六条 P1 的复现测试（2026-11-12 审查）。

geo-radar 的份额是「数出来的」，抽取漏一个就是份额少算一分。
P0-12 的真实后果：提示词模板一半是中文，而中文里品牌名紧贴汉字时词边界不成立，
等于一半样本的品牌识别失效——报告会给出一个系统性偏低的份额，且看起来完全正常。
"""
from __future__ import annotations

import pytest

from georadar import store
from georadar.extract import find_mentions, sentiment_of
from georadar.models import Answer, Run
from georadar.prompts import generate
from georadar.report import markdown_report


def _answer(text: str) -> Answer:
    return Answer(prompt_id="p1", provider="mock", model="m", text=text)


def _brands(text: str, brands: list[str]) -> list[str]:
    return [m.brand for m in find_mentions(_answer(text), brands)]


# ---- P0-12：中文紧贴的品牌名必须检出 ----

@pytest.mark.parametrize("text", [
    "推荐Acme这个工具",
    "Acme的稳定性最好",
    "我更倾向Acme，价格便宜",
    "用 Acme 吧",
    "Acme 值得一试",
])
def test_brand_detected_in_chinese_context(text):
    got = _brands(text, ["Acme"])
    assert got == ["Acme"], f"「{text}」应检出 Acme，实际 {got}"


def test_brand_not_detected_inside_a_longer_latin_word():
    # 正对照：放宽边界不能把 AcmeCorp / myAcme 也算成 Acme
    got = _brands("AcmeCorp 与 myAcme 都不是 Acme", ["Acme"])
    assert got == ["Acme"], f"只应命中独立出现的 Acme，实际 {got}"


def test_brand_with_punctuation_still_matched():
    got = _brands("看看 Bill.com 和 The Prompting Company",
                  ["Bill.com", "The Prompting Company"])
    assert set(got) == {"Bill.com", "The Prompting Company"}


def test_chinese_brand_name_matched():
    assert _brands("推荐用飞书做协同", ["飞书"]) == ["飞书"]


# ---- P1：情感词不能子串误命中 ----

def test_sentiment_does_not_match_top_inside_desktop():
    assert sentiment_of("A desktop app") == 0.0, "desktop 里的 top 不是褒义词"
    assert sentiment_of("the best desktop app") > 0


# ---- P1：run_id 同秒不重复 ----

def test_run_ids_are_unique_within_same_second():
    ids = {store.new_run_id() for _ in range(5)}
    assert len(ids) == 5, f"同秒产生的 run_id 必须互不相同：{ids}"


# ---- P1：同一 run 重存不能把 mention 翻倍 ----

def test_save_run_is_idempotent_for_mentions(tmp_path):
    conn = store.connect(tmp_path / "geo.db")
    run = Run(run_id="r1", brand="Acme", category="expense",
              competitors=["Beta"], provider="mock", created_at="2026-11-13T00:00:00Z")
    a = _answer("推荐 Acme 与 Beta")
    run.answers.append(a)
    mentions = find_mentions(a, ["Acme", "Beta"])
    store.save_run(conn, run, mentions)
    store.save_run(conn, run, mentions)
    _, loaded = store.load_run(conn, "r1")
    assert len(loaded) == 2, f"同一 run 重存不能产生重复 mention，实际 {len(loaded)}"


# ---- P1：领先时不能写「落后 -53.8%」 ----

def test_report_does_not_say_lagging_with_negative_gap():
    from georadar.metrics import brand_stats
    mentions = find_mentions(_answer("Acme Acme Beta"), ["Acme", "Beta"])
    stats = brand_stats(mentions, prompts_total=1)
    md = markdown_report("Acme", "expense", ["Beta"], stats, mentions, [], 1)
    assert "落后 -" not in md, "领先品牌不能写成「落后 -…%」"


# ---- P1：limit=-1 不能静默丢一条 ----

def test_negative_limit_is_rejected_loudly():
    with pytest.raises(ValueError):
        generate("expense", limit=-1)


# ---- P1：互为前缀的品牌不能占两个位次 ----

def test_prefix_brands_do_not_double_count_one_mention():
    ms = find_mentions(_answer("推荐 Bill.com 做账"), ["Bill", "Bill.com"])
    assert [m.brand for m in ms] == ["Bill.com"], "同一处只应记最长的那个品牌"
    assert [m.position for m in ms] == [1]
