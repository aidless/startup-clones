"""「打磨」过程中实测发现的四个缺陷的复现测试（先红后绿）。

四条都不是假想出来的 —— 每一条都是把真实语料/真实 run 跑一遍之后，
数据与报告对不上才发现的：

1. 每品牌只取**首次**出现，若首次出现落在更长品牌名内部，被 span 去重丢掉后
   这个品牌就整条消失（`Bill` 在 "Bill.com … Bill Gates … bill." 里判未提及）。
2. 同一品牌在一段回答里出现多次时，只应记一条 mention（口径是「一次回答里是否出现」），
   改完 1 之后必须仍然成立，否则份额被重复计数撑大。
3. `mentions` 表主键是 (run_id, prompt_id, brand)，把同一 prompt 的多次采样
   （run_index=0/1/2）压成一条：内存里 72 条 → 落库 32 条，`report --run-id`
   的份额/位次与 `run` 当时打印的不是同一个数。
4. 我们与竞品声量完全相等时，报表走 `else` 分支印「落后 **X** 声量 **0.0%**」。
"""
from __future__ import annotations

from georadar import metrics, report, store
from georadar.extract import find_mentions
from georadar.models import Answer, Mention, Run


def _answer(text: str, prompt_id: str = "p1", run_index: int = 0) -> Answer:
    return Answer(prompt_id=prompt_id, provider="mock", model="mock-1", text=text,
                  run_index=run_index)


def test_brand_after_longer_brand_is_not_lost():
    """`Bill` 的首次出现被 `Bill.com` 完全包住，但它后面还独立出现过一次。"""
    answer = _answer("Bill.com is fine. Bill Gates also uses it.")
    mentions = find_mentions(answer, ["Bill", "Bill.com"])
    brands = [m.brand for m in mentions]
    assert "Bill.com" in brands
    assert "Bill" in brands, f"Bill 整条丢失，只抽到 {brands}"
    bill = next(m for m in mentions if m.brand == "Bill")
    assert bill.char_offset == answer.text.index("Bill Gates"), "取到的不是那次独立出现"
    # 位次：Bill.com 在前，Bill 在后
    assert next(m.position for m in mentions if m.brand == "Bill.com") == 1
    assert bill.position == 2


def test_repeated_brand_in_one_answer_is_one_mention():
    """同一段回答里出现三次也只记一条 —— 口径是「这次回答提到了没」。"""
    answer = _answer("Acme 很好用。Acme 便宜。我还是选 Acme。")
    mentions = find_mentions(answer, ["Acme"])
    assert len(mentions) == 1
    assert mentions[0].char_offset == answer.text.index("Acme")


def test_store_keeps_every_sample(tmp_path):
    """同一 prompt 的三次采样各自有 mention，落库后条数不能塌缩。"""
    conn = store.connect(tmp_path / "g.db")
    run = Run(run_id="run-test", brand="Acme", category="AI SRE",
              competitors=["Traversal"], provider="mock", created_at="2026-11-13T00:00:00+00:00")
    mentions = []
    for run_index in range(3):
        answer = _answer("Acme 不错。", prompt_id="p1", run_index=run_index)
        run.answers.append(answer)
        mentions.extend(find_mentions(answer, ["Acme"]))
    assert len(mentions) == 3

    store.save_run(conn, run, mentions)
    _run, loaded = store.load_run(conn, "run-test")
    assert len(loaded) == 3, f"落库后只剩 {len(loaded)} 条：同一 prompt 的多次采样被主键压掉了"
    assert {m.run_index for m in loaded} == {0, 1, 2}


def test_tie_is_reported_as_even_not_behind():
    """声量完全相等时不能印「落后 0.0%」。"""
    mentions = [
        Mention(prompt_id="p1", brand="Acme", position=1, char_offset=0, sentiment=0.0),
        Mention(prompt_id="p1", brand="Traversal", position=2, char_offset=20, sentiment=0.0),
    ]
    stats = metrics.brand_stats(mentions, 1)
    gap = metrics.gap_report(stats, "Acme", ["Traversal"])
    assert gap["gap_sov"] == 0

    md = report.markdown_report("Acme", "AI SRE", ["Traversal"], stats, mentions,
                                [_answer("Acme 与 Traversal 都在。")], 1)
    assert "落后 **Traversal** 声量 **0.0%**" not in md
    assert "持平" in md
