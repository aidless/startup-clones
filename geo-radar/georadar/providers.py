"""LLM 提供方适配。

设计要点：
1. 统一接口，便于横向比较不同模型对同一提示词的品牌偏向。
2. MockProvider 是确定性实现 —— 没有 API key 也能跑测试、跑 demo。
3. OpenAICompatProvider 走 /chat/completions，任何兼容端点（OpenAI / DeepSeek /
   Kimi / vLLM / Ollama）都能接，不绑定厂商。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from abc import ABC, abstractmethod

from .models import Answer, Citation

URL_RE = re.compile(r"https?://[^\s)\]\"'>]+")


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return (m.group(1) if m else url).lower().removeprefix("www.")


class Provider(ABC):
    name = "base"

    @abstractmethod
    def complete(self, prompt: str, model: str, run_index: int = 0) -> Answer: ...


class MockProvider(Provider):
    """确定性假模型：同一 prompt + run_index 永远给出同一段文本。

    文本里按「伪随机」顺序罗列品牌，用来验证抽取/排名/份额计算链路。
    run_index 参与随机种子，模拟真实模型采样带来的排名波动。
    """

    name = "mock"

    def __init__(self, brands: list[str], seed: int = 7):
        self.brands = list(brands)
        self.seed = seed

    def complete(self, prompt: str, model: str = "mock-1", run_index: int = 0) -> Answer:
        h = int(hashlib.sha1(f"{prompt}|{model}".encode()).hexdigest()[:8], 16)
        rng = random.Random(self.seed * 100003 + h + run_index * 7919)
        ranked = self.brands[:]
        rng.shuffle(ranked)
        keep = ranked[: max(2, len(ranked) - 1)]  # 故意漏掉一个，制造「未被提及」

        lines = [f"针对「{prompt}」，目前主流选择包括："]
        for i, b in enumerate(keep, 1):
            lines.append(f"{i}. {b} —— 在该场景下表现稳定，适合直接评估。")
        lines.append("综合来看，建议先做小范围试用再决定。")
        text = "\n".join(lines)

        d1 = rng.choice(["g2.com", "reddit.com", "zhihu.com", "news.ycombinator.com"])
        d2 = rng.choice(["gartner.com", "forrester.com", "producthunt.com"])
        citations = [
            Citation(url=f"https://{d1}/s/{h % 9973}", domain=d1, title="community thread"),
            Citation(url=f"https://{d2}/report/{rng.randint(1000,9999)}", domain=d2, title="industry report"),
        ]
        return Answer(
            prompt_id="", provider=self.name, model=model, text=text,
            citations=citations, run_index=run_index,
        )


class OpenAICompatProvider(Provider):
    """任意 OpenAI 兼容端点。环境变量：GEO_API_KEY / GEO_BASE_URL。"""

    name = "openai-compat"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 60.0):
        self.api_key = api_key or os.environ.get("GEO_API_KEY", "")
        self.base_url = (base_url or os.environ.get("GEO_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str, model: str = "gpt-4o-mini", run_index: int = 0) -> Answer:
        import httpx

        if not self.api_key:
            raise RuntimeError("缺少 GEO_API_KEY，改用 --provider mock")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful analyst answering buying questions. Cite sources with URLs."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7 if run_index else 0.2,
        }
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        citations = [Citation(url=u, domain=_domain(u)) for u in urls]
        return Answer(prompt_id="", provider=self.name, model=model, text=text,
                      citations=citations, run_index=run_index)


class OllamaProvider(Provider):
    """本机 Ollama。用一个模型都跑不起的环境证明不了「多模型不一致」这件事。

    GEO 的真实风险不是「某个模型怎么说」，而是「换个模型结论就变」。
    所以本地能跑多个小模型，比接一个贵的大模型更有价值。
    """

    name = "ollama"

    def __init__(self, host: str | None = None, timeout: float = 300.0):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str, model: str = "qwen3:8b", run_index: int = 0) -> Answer:
        import httpx

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            # think=False 是必须的：qwen3 这类混合推理模型默认先吐 thinking，
            # 会把 num_predict 吃光，response 返回空串。实测 8 条提示词全空。
            "think": False,
            "options": {"temperature": 0.7 if run_index else 0.2, "num_predict": 400},
        }
        r = httpx.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        text = (data.get("response") or "").strip()
        if not text:
            # 空答案不是「没提到任何品牌」，是这次采样失败。混为一谈会污染份额统计。
            raise RuntimeError(
                f"模型 {model} 返回空文本（done_reason={data.get('done_reason')}，"
                f"thinking 长度={len(data.get('thinking') or '')}）")
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        citations = [Citation(url=u, domain=_domain(u)) for u in urls]
        return Answer(prompt_id="", provider=self.name, model=model, text=text,
                      citations=citations, run_index=run_index)


def build_provider(kind: str, brands: list[str], **kw) -> Provider:
    if kind == "mock":
        return MockProvider(brands, seed=int(kw.get("seed", 7)))
    if kind == "ollama":
        return OllamaProvider(host=kw.get("base_url") or kw.get("host"))
    if kind in {"openai", "openai-compat", "deepseek", "kimi", "vllm"}:
        return OpenAICompatProvider(api_key=kw.get("api_key"), base_url=kw.get("base_url"))
    raise ValueError(f"未知 provider: {kind}")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
