from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class Prompt:
    """一条用于探测 AI 回答的提示词。"""

    id: str
    text: str
    intent: str = "discovery"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    url: str
    domain: str
    title: str = ""


@dataclass
class Answer:
    prompt_id: str
    provider: str
    model: str
    text: str
    citations: list[Citation] = field(default_factory=list)
    run_index: int = 0


@dataclass(frozen=True)
class Mention:
    """品牌在一次回答中的出现记录。"""

    prompt_id: str
    brand: str
    position: int        # 1 = 第一个被提到的品牌
    char_offset: int
    sentiment: float     # -1 .. 1
    context: str = ""
    run_index: int = 0   # 同一条 prompt 的第几次采样（repeat>1 时必须区分）

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Run:
    run_id: str
    brand: str
    category: str
    competitors: list[str]
    provider: str
    created_at: str
    answers: list[Answer] = field(default_factory=list)
