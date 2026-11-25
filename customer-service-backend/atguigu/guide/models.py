from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atguigu.domain.message import MessageObject


@dataclass(slots=True)
class ShoppingNeed:
    """导购需求：由 NeedAgent 从自然语言中抽取出的结构化条件。"""

    raw_query: str
    category: str | None = None
    keywords: list[str] = field(default_factory=list)
    budget_min: float | None = None
    budget_max: float | None = None
    scenario: str | None = None
    must_have: list[str] = field(default_factory=list)

    @property
    def search_terms(self) -> list[str]:
        terms = [term for term in [self.category, *self.keywords] if term]
        return list(dict.fromkeys(terms))

    @property
    def has_budget(self) -> bool:
        return self.budget_min is not None or self.budget_max is not None

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "category": self.category,
            "keywords": self.keywords,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "scenario": self.scenario,
            "must_have": self.must_have,
        }


@dataclass(slots=True)
class ProductCandidate:
    """目录 Agent 召回的商品，附带打分和推荐理由。"""

    product_id: str
    title: str
    price: float | None
    description: str = ""
    stock_status: str = ""
    cover_url: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_message_object(self, reason: str = "") -> MessageObject:
        attributes: dict[str, Any] = {
            "price": self.price,
            "stock_status": self.stock_status,
            "cover_url": self.cover_url,
        }
        for key, value in self.attributes.items():
            attributes.setdefault(key, value)
        attributes["recommend_reason"] = reason or "；".join(self.reasons)
        return MessageObject(
            type="product",
            id=self.product_id,
            title=self.title,
            attributes=attributes,
        )


@dataclass(slots=True)
class PolicyAdvice:
    """政策 Agent 的输出：与当前导购场景相关的购买提示。"""

    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(f"- {note}" for note in self.notes)
