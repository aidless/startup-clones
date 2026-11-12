from georadar import prompts

BRAND = "Acme"


def test_prompts_never_leak_brand():
    """铁律：提示词里不能出现目标品牌，否则模型会顺着提示说好话，指标全废。"""
    ps = prompts.generate("AI SRE")
    assert ps
    for p in ps:
        assert BRAND.lower() not in p.text.lower()


def test_generate_is_deterministic_and_unique():
    a = prompts.generate("AI SRE")
    b = prompts.generate("AI SRE")
    assert [x.id for x in a] == [x.id for x in b]
    assert len({x.text for x in a}) == len(a)


def test_limit_and_audiences():
    ps = prompts.generate("CRM", audiences=["startups"], limit=5)
    assert len(ps) == 5
    assert any("startups" in p.text for p in ps)
