import pytest

from georadar import metrics
from georadar.extract import find_mentions, sentiment_of
from georadar.models import Answer
from georadar.providers import MockProvider

BRANDS = ["Acme", "Traversal", "Rootly"]


def test_mention_position_follows_text_order():
    a = Answer(prompt_id="p1", provider="mock", model="m",
               text="Rootly is solid. Acme is the leading option. Traversal is expensive.")
    ms = find_mentions(a, BRANDS)
    assert [m.brand for m in ms] == ["Rootly", "Acme", "Traversal"]
    assert [m.position for m in ms] == [1, 2, 3]
    assert ms[0].char_offset < ms[1].char_offset


def test_word_boundary_no_false_positive():
    a = Answer(prompt_id="p1", provider="mock", model="m", text="Acmezilla and Acme-corp are unrelated.")
    assert find_mentions(a, ["Acme"]) == []


def test_sentiment_is_bounded():
    assert sentiment_of("the leading, reliable, best option") == 1.0
    assert sentiment_of("expensive, weak, limited") == -1.0
    assert sentiment_of("it exists") == 0.0


def test_share_of_voice_sums_to_one():
    prov = MockProvider(BRANDS, seed=3)
    mentions = []
    for i in range(20):
        a = prov.complete(f"best tool {i}", run_index=i)
        a.prompt_id = f"p{i}"
        mentions.extend(find_mentions(a, BRANDS))
    stats = metrics.brand_stats(mentions, prompts_total=20)
    assert stats
    total = sum(s.share_of_voice for s in stats.values())
    assert total == pytest.approx(1.0, abs=1e-3)


def test_visibility_rate_denominator():
    prov = MockProvider(BRANDS, seed=11)
    mentions = []
    for i in range(10):
        a = prov.complete(f"q{i}", run_index=i)
        a.prompt_id = f"p{i}"
        mentions.extend(find_mentions(a, BRANDS))
    stats = metrics.brand_stats(mentions, prompts_total=10)
    for s in stats.values():
        assert 0.0 <= metrics.visibility_rate(stats, s.brand, 10) <= 1.0
