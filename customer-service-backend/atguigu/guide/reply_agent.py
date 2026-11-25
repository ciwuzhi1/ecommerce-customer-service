from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.output_parsers import StrOutputParser

from atguigu.guide.models import PolicyAdvice, ProductCandidate, ShoppingNeed
from atguigu.prompts import load_prompt_template

logger = logging.getLogger(__name__)


class ReplyAgent:
    """回复 Agent：把需求、候选商品和政策提示合成一段自然的导购话术。"""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm
        self.output_parser = StrOutputParser()
        self.prompt = load_prompt_template("guide/reply") if llm is not None else None

    async def compose(
        self,
        need: ShoppingNeed,
        candidates: list[ProductCandidate],
        policy: PolicyAdvice,
    ) -> str:
        if self.llm is None or self.prompt is None or not candidates:
            return self.fallback(need, candidates, policy)

        try:
            text = await (self.prompt | self.llm | self.output_parser).ainvoke(
                {
                    "need_json": json.dumps(need.to_prompt_dict(), ensure_ascii=False),
                    "candidates_text": _render_candidates(candidates),
                    "policy_text": policy.text or "无",
                }
            )
            return text.strip() or self.fallback(need, candidates, policy)
        except Exception as exc:
            logger.warning("guide.reply_agent fallback: %s", exc)
            return self.fallback(need, candidates, policy)

    @staticmethod
    def fallback(
        need: ShoppingNeed,
        candidates: list[ProductCandidate],
        policy: PolicyAdvice,
    ) -> str:
        if not candidates:
            parts = [f"我暂时没有找到完全符合「{need.raw_query}」的商品。"]
            if need.budget_max is not None:
                parts.append(f"当前筛选的预算上限是 ¥{need.budget_max:g}，")
                parts.append("也可以适当放宽预算再找。")
            parts.append("你可以补充一下品类、预算或使用场景，我再帮你挑。")
            return "".join(parts)

        names = "、".join(f"「{candidate.title}」" for candidate in candidates[:3])
        parts = [f"根据你的需求，我优先推荐{names}。"]
        top = candidates[0]
        if top.reasons:
            parts.append(f"其中「{top.title}」的优势是：{'；'.join(top.reasons[:2])}。")
        if policy.notes:
            parts.append(f"下单前可以留意：{policy.notes[0]}")
        parts.append("你可以点开商品卡片看规格，也可以告诉我更看重价格还是性能。")
        return "".join(parts)


def _render_candidates(candidates: list[ProductCandidate]) -> str:
    lines: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        price = f"¥{candidate.price:g}" if candidate.price is not None else "价格未知"
        specs = "，".join(
            f"{key}{value}" for key, value in list(candidate.attributes.items())[:3]
        ) or "规格未提供"
        lines.append(
            f"{index}. {candidate.title}｜{price}｜{candidate.stock_status or '库存未知'}"
            f"｜{specs}｜{candidate.description[:60]}"
            f"｜匹配理由：{'；'.join(candidate.reasons) or '综合匹配'}"
        )
    return "\n".join(lines)
