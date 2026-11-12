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


def test_ollama_provider_parses_response(monkeypatch):
    """不发真请求：只验解析与 URL 抽取。"""
    import httpx

    from georadar.providers import OllamaProvider

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "1. Ramp https://ramp.com\n2. Brex https://brex.com"}

    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["model"] = json["model"]
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    a = OllamaProvider(host="http://127.0.0.1:11434").complete("q", model="qwen3:8b")
    assert seen["url"].endswith("/api/generate")
    assert seen["model"] == "qwen3:8b"
    assert [c.domain for c in a.citations] == ["ramp.com", "brex.com"]
    assert a.provider == "ollama"


def test_ollama_empty_response_raises(monkeypatch):
    """空返回必须报错：把它当成「没提到品牌」会让份额统计失真。"""
    import httpx
    import pytest

    from georadar.providers import OllamaProvider

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "", "thinking": "长思考...", "done_reason": "length"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    with pytest.raises(RuntimeError) as ei:
        OllamaProvider().complete("q", model="qwen3:8b")
    assert "空文本" in str(ei.value)


def test_magpie_provider_wiring(monkeypatch):
    """本机网关不校验 token，但客户端要求非空 key；超时默认要比 SDK 更宽。"""
    from georadar.providers import OpenAICompatProvider, build_provider

    monkeypatch.delenv("MAGPIE_API_KEY", raising=False)
    monkeypatch.delenv("MAGPIE_BASE_URL", raising=False)
    p = build_provider("magpie", ["Ramp"])
    assert isinstance(p, OpenAICompatProvider)
    assert p.base_url == "http://127.0.0.1:3425/v1"
    assert p.api_key == "local"
    assert p.timeout >= 120
