from __future__ import annotations

import asyncio

from atguigu.guide.models import PolicyAdvice, ShoppingNeed

_CATEGORY_TIPS: dict[str, str] = {
    "手机": "同价位优先比较存储容量、网络制式和电池续航，再看影像能力。",
    "耳机": "通勤场景优先看降噪深度和佩戴舒适度，运动场景留意防水等级。",
    "家电": "先确认功率、容量与家里的插座和摆放空间是否匹配。",
    "手表": "先确认与手机生态的兼容性，再按手腕尺寸选择表壳大小。",
    "保暖": "注意发热时长和适用部位，敏感肌建议先确认材质。",
    "数码": "先明确主要用途，再在预算内平衡性能和便携性。",
}

_BASE_TIPS = [
    "下单前确认收货地址，常规商品一般 48 小时内发货，偏远地区以页面提示为准。",
    "支持 7 天无理由退换，商品需保持完好，运费承担以平台规则为准。",
]


class PolicyAgent:
    """政策 Agent：并发执行期间提供配送、退换和选品维度的提示。"""

    async def advice(self, need: ShoppingNeed) -> PolicyAdvice:
        # 这里保留异步签名，后续可替换为 FAQ/RAG 检索而不影响编排层。
        await asyncio.sleep(0)
        notes: list[str] = []

        if need.category and need.category in _CATEGORY_TIPS:
            notes.append(_CATEGORY_TIPS[need.category])
        if need.budget_max is not None:
            notes.append(f"预算上限按 ¥{need.budget_max:g} 控制，超出预算的商品不会优先推荐。")
        notes.extend(_BASE_TIPS)
        if need.must_have:
            notes.append(
                "你明确提到的「" + "、".join(need.must_have[:3]) + "」建议在商品详情页再次确认。"
            )

        deduped: list[str] = []
        for note in notes:
            if note not in deduped:
                deduped.append(note)
        return PolicyAdvice(notes=deduped[:4])
