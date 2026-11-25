from __future__ import annotations

import asyncio
import logging
from typing import Any

from atguigu.conf.config import settings
from atguigu.guide.models import ProductCandidate, ShoppingNeed
from atguigu.infrastructure.http_client import http_client

logger = logging.getLogger(__name__)


class CatalogAgent:
    """目录 Agent：把一份需求拆成多个检索子任务，并发查询电商服务后合并去重。"""

    def __init__(self, *, per_query_timeout: float = 6.0, query_limit: int = 8) -> None:
        self.per_query_timeout = per_query_timeout
        self.query_limit = query_limit

    async def search(self, need: ShoppingNeed) -> list[ProductCandidate]:
        queries = self._build_queries(need)
        if not queries:
            return []

        results = await asyncio.gather(
            *(self._search_one(query) for query in queries),
            return_exceptions=True,
        )

        merged: dict[str, ProductCandidate] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("guide.catalog_agent query failed: %s", result)
                continue
            for candidate in result:
                existing = merged.get(candidate.product_id)
                if existing is None:
                    merged[candidate.product_id] = candidate
                    continue
                if candidate.score > existing.score:
                    merged[candidate.product_id] = candidate

        for candidate in merged.values():
            score, reasons = self._score(candidate, need)
            candidate.score = score
            candidate.reasons = reasons

        ranked = sorted(
            merged.values(),
            key=lambda item: (-item.score, item.price if item.price is not None else float("inf")),
        )
        return ranked[: self.query_limit]

    def _build_queries(self, need: ShoppingNeed) -> list[dict[str, Any]]:
        terms = need.search_terms
        price_filter: dict[str, Any] = {}
        if need.budget_min is not None:
            price_filter["min_price"] = need.budget_min
        if need.budget_max is not None:
            price_filter["max_price"] = need.budget_max

        raw_queries: list[dict[str, Any]] = []
        if terms:
            raw_queries.append({"keyword": " ".join(terms)})
            raw_queries.extend({"keyword": term} for term in terms[:3])
        if need.category:
            raw_queries.append({"category": need.category})
        if need.must_have:
            raw_queries.append({"keyword": " ".join(need.must_have[:2])})
        if not raw_queries:
            raw_queries.append({"keyword": need.raw_query})

        queries: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, Any], ...]] = set()
        for query in raw_queries:
            merged = {**query, **price_filter, "limit": self.query_limit}
            key = tuple(sorted(merged.items()))
            if key in seen:
                continue
            seen.add(key)
            queries.append(merged)
        return queries[:5]

    async def _search_one(self, query: dict[str, Any]) -> list[ProductCandidate]:
        url = f"{settings.commerce_api_base_url.rstrip('/')}/products/search"
        response = await asyncio.wait_for(
            http_client.get(url, params=query),
            timeout=self.per_query_timeout,
        )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        products = data.get("products") if isinstance(data, dict) else None
        if not isinstance(products, list):
            return []
        return [self._to_candidate(item) for item in products if isinstance(item, dict)]

    @staticmethod
    def _to_candidate(product: dict[str, Any]) -> ProductCandidate:
        attributes = product.get("attributes")
        return ProductCandidate(
            product_id=str(product.get("product_id") or ""),
            title=str(product.get("title") or ""),
            price=_to_float(product.get("price")),
            description=str(product.get("description") or ""),
            stock_status=str(product.get("stock_status") or ""),
            cover_url=product.get("cover_url"),
            attributes=attributes if isinstance(attributes, dict) else {},
        )

    @staticmethod
    def _score(candidate: ProductCandidate, need: ShoppingNeed) -> tuple[float, list[str]]:
        haystack = " ".join(
            [
                candidate.title,
                candidate.description,
                " ".join(str(value) for value in candidate.attributes.values()),
            ]
        )
        score = 0.0
        reasons: list[str] = []

        for term in need.search_terms:
            if term in candidate.title:
                score += 3.0
                reasons.append(f"标题匹配「{term}」")
            elif term in haystack:
                score += 1.5
                reasons.append(f"详情匹配「{term}」")

        for term in need.must_have:
            if term in haystack:
                score += 1.5
                reasons.append(f"满足「{term}」")

        if candidate.price is not None and need.has_budget:
            within_min = need.budget_min is None or candidate.price >= need.budget_min
            within_max = need.budget_max is None or candidate.price <= need.budget_max
            if within_min and within_max:
                score += 2.0
                reasons.append(f"价格 ¥{candidate.price:g} 在预算内")
            else:
                score -= 2.0

        if "有货" in candidate.stock_status:
            score += 1.0
            reasons.append("当前有货")

        return score, reasons[:3]


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
