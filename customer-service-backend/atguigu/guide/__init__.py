from __future__ import annotations

from typing import Any

from atguigu.guide.orchestrator import ShoppingGuideOrchestrator

_default_guide: ShoppingGuideOrchestrator | None = None


def build_shopping_guide(llm: Any | None = None) -> ShoppingGuideOrchestrator:
    return ShoppingGuideOrchestrator(llm=llm)


def get_shopping_guide() -> ShoppingGuideOrchestrator:
    """动作注册表不带参数实例化，这里延迟构建共享编排器。"""
    global _default_guide
    if _default_guide is None:
        from atguigu.infrastructure.llm import llm

        _default_guide = build_shopping_guide(llm=llm)
    return _default_guide


__all__ = ["ShoppingGuideOrchestrator", "build_shopping_guide", "get_shopping_guide"]
