from __future__ import annotations

from typing import Any

from atguigu.domain.message import BotMessage, Message
from atguigu.domain.state import DialogueState
from atguigu.knowledge.context_builder import KnowledgeContextBuilder
from atguigu.knowledge.planner import KnowledgePlanner
from atguigu.knowledge.provider import KnowledgeProvider, KnowledgeProviderRegistry
from atguigu.knowledge.responder import KnowledgeResponder

RECOMMENDATION_INTENT = "product_recommendation"


class KnowledgeHandler:
    def __init__(
        self,
        *,
        responder: KnowledgeResponder,
        providers: list[KnowledgeProvider],
        context_builder: KnowledgeContextBuilder | None = None,
        planner: KnowledgePlanner | None = None,
        shopping_guide: Any | None = None,
    ) -> None:
        self.responder = responder
        self.registry = KnowledgeProviderRegistry(providers)
        self.context_builder = context_builder or KnowledgeContextBuilder()
        self.planner = planner or KnowledgePlanner()
        self.shopping_guide = shopping_guide

    async def handle(
        self,
        *,
        message: Message,
        state: DialogueState,
        intent: str | None = None,
    ) -> list[BotMessage]:
        context = self.context_builder.build(message, state, intent=intent)

        # 导购意图走多 Agent 编排，而不是普通知识检索。
        if intent == RECOMMENDATION_INTENT and self.shopping_guide is not None:
            return await self.shopping_guide.guide(context.user_message)

        plan = self.planner.plan(context)
        chunks = []
        for provider_id in plan.provider_ids:
            provider = self.registry.get(provider_id)
            if provider is not None:
                chunks.extend(await provider.retrieve(context.user_message, context))
        return await self.responder.respond(context, chunks)
