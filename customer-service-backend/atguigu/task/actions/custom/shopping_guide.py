from atguigu.domain.message import BotMessage
from atguigu.domain.state import DialogueState
from atguigu.guide import get_shopping_guide
from atguigu.task.actions.base import Action, ActionResult


class ShoppingGuideAction(Action):
    """导购动作：把收集到的需求交给多 Agent 编排器，返回话术和商品卡片。"""

    name = "action_shopping_guide"

    async def run(self, state: DialogueState, **kwargs: object) -> ActionResult:
        query = str(state.get_slot("shopping_need") or "").strip()
        budget = state.get_slot("budget")
        if not query:
            return ActionResult(
                messages=[BotMessage(text="先告诉我想买什么，我才能帮你挑商品。")]
            )

        messages = await get_shopping_guide().guide(
            query,
            budget_hint=str(budget) if budget not in (None, "") else None,
        )
        return ActionResult(messages=messages)
