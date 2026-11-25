from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, TypeVar

from atguigu.domain.message import BotMessage
from atguigu.guide.catalog_agent import CatalogAgent
from atguigu.guide.models import PolicyAdvice, ProductCandidate, ShoppingNeed
from atguigu.guide.need_agent import NeedAgent
from atguigu.guide.policy_agent import PolicyAgent
from atguigu.guide.reply_agent import ReplyAgent

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NEED_TIMEOUT = 12.0
_CATALOG_TIMEOUT = 8.0
_POLICY_TIMEOUT = 3.0
_REPLY_TIMEOUT = 15.0


class ShoppingGuideOrchestrator:
    """导购编排器：串起需求解析 → 并发专家 Agent → 融合回复。

    并发点：
      1. NeedAgent 完成后，CatalogAgent 与 PolicyAgent 通过 asyncio.gather 同时执行；
      2. CatalogAgent 内部把多个检索条件拆成子任务，再并发请求电商服务；
      3. 每个 Agent 有独立超时和失败隔离，单个 Agent 超时不会拖垮整轮导购。
    """

    def __init__(
        self,
        *,
        llm: Any | None = None,
        need_agent: NeedAgent | None = None,
        catalog_agent: CatalogAgent | None = None,
        policy_agent: PolicyAgent | None = None,
        reply_agent: ReplyAgent | None = None,
        max_products: int = 3,
    ) -> None:
        self.need_agent = need_agent or NeedAgent(llm=llm)
        self.catalog_agent = catalog_agent or CatalogAgent()
        self.policy_agent = policy_agent or PolicyAgent()
        self.reply_agent = reply_agent or ReplyAgent(llm=llm)
        self.max_products = max_products

    async def guide(
        self,
        query: str,
        *,
        budget_hint: str | None = None,
    ) -> list[BotMessage]:
        query = (query or "").strip()
        if not query:
            return [BotMessage(text="告诉我想买什么、预算大概多少，我来帮你挑几件合适的。")]

        started_at = time.perf_counter()
        need = await self._analyze_need(query, budget_hint)

        catalog_result, policy_result = await asyncio.gather(
            self._run_agent("catalog", self.catalog_agent.search(need), _CATALOG_TIMEOUT, []),
            self._run_agent("policy", self.policy_agent.advice(need), _POLICY_TIMEOUT, PolicyAdvice()),
        )
        candidates: list[ProductCandidate] = [
            item for item in catalog_result if isinstance(item, ProductCandidate)
        ]
        policy = policy_result if isinstance(policy_result, PolicyAdvice) else PolicyAdvice()
        top_candidates = candidates[: self.max_products]

        reply = await self._run_agent(
            "reply",
            self.reply_agent.compose(need, top_candidates, policy),
            _REPLY_TIMEOUT,
            "",
        )
        if not reply:
            reply = self.reply_agent.fallback(need, top_candidates, policy)

        messages: list[BotMessage] = [BotMessage(text=reply)]
        for candidate in top_candidates:
            messages.append(
                BotMessage(
                    object=candidate.to_message_object(
                        reason="；".join(candidate.reasons[:2]),
                    )
                )
            )

        logger.info(
            "guide.done category=%s keywords=%s candidates=%d cost_ms=%.0f",
            need.category,
            ",".join(need.keywords),
            len(candidates),
            (time.perf_counter() - started_at) * 1000,
        )
        return messages

    async def _analyze_need(self, query: str, budget_hint: str | None) -> ShoppingNeed:
        started_at = time.perf_counter()
        try:
            need = await asyncio.wait_for(
                self.need_agent.analyze(query, budget_hint),
                timeout=_NEED_TIMEOUT,
            )
            logger.info(
                "guide.agent name=need status=ok cost_ms=%.0f",
                (time.perf_counter() - started_at) * 1000,
            )
            return need
        except Exception as exc:
            logger.warning(
                "guide.agent name=need status=failed cost_ms=%.0f error=%s",
                (time.perf_counter() - started_at) * 1000,
                exc,
            )
            return self.need_agent.heuristic(query, budget_hint)

    async def _run_agent(
        self,
        name: str,
        awaitable: Awaitable[T],
        timeout: float,
        default: T,
    ) -> T:
        started_at = time.perf_counter()
        try:
            result = await asyncio.wait_for(awaitable, timeout=timeout)
            logger.info(
                "guide.agent name=%s status=ok cost_ms=%.0f",
                name,
                (time.perf_counter() - started_at) * 1000,
            )
            return result
        except Exception as exc:
            logger.warning(
                "guide.agent name=%s status=failed cost_ms=%.0f error=%s",
                name,
                (time.perf_counter() - started_at) * 1000,
                exc,
            )
            return default
