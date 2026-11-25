from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.output_parsers import StrOutputParser

from atguigu.guide.models import ShoppingNeed
from atguigu.prompts import load_prompt_template

logger = logging.getLogger(__name__)

_CATEGORY_LEXICON: dict[str, tuple[str, ...]] = {
    "手机": ("手机", "iphone", "苹果", "安卓", "华为", "小米"),
    "耳机": ("耳机", "降噪", "蓝牙耳机"),
    "家电": ("家电", "水壶", "电热水壶", "厨房", "电器"),
    "手表": ("手表", "watch", "腕表"),
    "保暖": ("保暖", "暖宝宝", "发热", "冬天", "秋冬"),
    "数码": ("数码", "平板", "电脑", "相机"),
}

_STOPWORDS = {
    "我想", "想买", "买个", "买一个", "帮我", "推荐", "一个", "一款", "一下",
    "有没有", "什么", "适合", "比较", "好的", "可以", "需要", "希望", "最好",
    "预算", "左右", "以内", "以下", "之内", "元", "块", "的", "吗", "呢", "吧",
    "和", "或", "要", "东西", "商品",
}

_ATTRIBUTE_WORDS = (
    "降噪", "通勤", "送礼", "礼物", "女朋友", "男朋友", "生日", "大容量",
    "轻便", "续航", "拍照", "游戏", "办公", "学生", "运动", "旅行", "防水",
    "保暖", "发热", "恒温", "快充", "无线", "便携",
)

_SCENARIO_MAP = {
    "通勤": "通勤",
    "送礼": "送礼",
    "礼物": "送礼",
    "生日": "送礼",
    "办公": "办公",
    "学生": "学生",
    "运动": "运动",
    "旅行": "旅行",
}


class NeedAgent:
    """把用户的一句话解析为结构化导购需求；LLM 不可用时退回规则解析。"""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm
        self.output_parser = StrOutputParser()
        self.prompt = load_prompt_template("guide/need_extraction") if llm is not None else None

    async def analyze(self, query: str, budget_hint: str | None = None) -> ShoppingNeed:
        fallback = self.heuristic(query, budget_hint)
        if self.llm is None or self.prompt is None:
            return fallback

        try:
            raw = await (self.prompt | self.llm | self.output_parser).ainvoke(
                {"user_message": query, "budget_hint": budget_hint or ""}
            )
            payload = json.loads(_strip_code_fences(raw))
            if not isinstance(payload, dict):
                raise ValueError("need extraction output must be an object")
            return self._merge_payload(query, payload, fallback)
        except Exception as exc:  # LLM 解析失败时保证导购流程仍可继续
            logger.warning("guide.need_agent fallback: %s", exc)
            return fallback

    @staticmethod
    def _merge_payload(
        query: str,
        payload: dict[str, Any],
        fallback: ShoppingNeed,
    ) -> ShoppingNeed:
        keywords = [str(item).strip() for item in payload.get("keywords") or [] if str(item).strip()]
        must_have = [str(item).strip() for item in payload.get("must_have") or [] if str(item).strip()]
        category = str(payload.get("category") or "").strip() or fallback.category
        budget_min = _to_float(payload.get("budget_min"))
        budget_max = _to_float(payload.get("budget_max"))

        return ShoppingNeed(
            raw_query=query,
            category=category,
            keywords=keywords or fallback.keywords,
            budget_min=budget_min if budget_min is not None else fallback.budget_min,
            budget_max=budget_max if budget_max is not None else fallback.budget_max,
            scenario=str(payload.get("scenario") or "").strip() or fallback.scenario,
            must_have=must_have,
        )

    @classmethod
    def heuristic(cls, query: str, budget_hint: str | None = None) -> ShoppingNeed:
        text = (query or "").strip()
        lowered = text.lower()

        category = None
        for name, aliases in _CATEGORY_LEXICON.items():
            if any(alias in lowered for alias in aliases):
                category = name
                break

        budget_min, budget_max = _parse_budget(text)
        if budget_hint:
            hint_min, hint_max = _parse_budget(str(budget_hint))
            budget_min = budget_min if budget_min is not None else hint_min
            budget_max = budget_max if budget_max is not None else hint_max

        keywords = _extract_keywords(text, category)
        must_have = [word for word in keywords if word in _ATTRIBUTE_WORDS]
        scenario = next(
            (value for word, value in _SCENARIO_MAP.items() if word in text),
            None,
        )

        return ShoppingNeed(
            raw_query=text,
            category=category,
            keywords=keywords,
            budget_min=budget_min,
            budget_max=budget_max,
            scenario=scenario,
            must_have=must_have[:3],
        )


def _strip_code_fences(payload: str) -> str:
    content = (payload or "").strip()
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return content


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_budget(text: str) -> tuple[float | None, float | None]:
    if not text:
        return None, None

    patterns = [
        (r"预算\s*(\d+(?:\.\d+)?)\s*[-~—到至]\s*(\d+(?:\.\d+)?)", True),
        (r"(\d+(?:\.\d+)?)\s*[-~—到至]\s*(\d+(?:\.\d+)?)\s*(?:元|块)", True),
        (r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|以下|左右|之内)", False),
        (r"不超过\s*(\d+(?:\.\d+)?)", False),
        (r"预算\s*(\d+(?:\.\d+)?)", False),
    ]
    for pattern, has_range in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        if has_range:
            return float(match.group(1)), float(match.group(2))
        return None, float(match.group(1))
    return None, None


def _extract_keywords(text: str, category: str | None) -> list[str]:
    keywords: list[str] = []

    # 1. 先命中内置的品类/属性词表，保证“降噪耳机”“通勤”这类词可检索。
    lexicon = [*_ATTRIBUTE_WORDS]
    for aliases in _CATEGORY_LEXICON.values():
        lexicon.extend(aliases)
    for word in sorted(lexicon, key=len, reverse=True):
        if word and word in text.lower() and word not in keywords:
            keywords.append(word)

    # 2. 英文/数字型号词，例如 iPhone、SKU10001。
    seen = {word.lower() for word in keywords}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9]+|\d{4,}", text or ""):
        if token.lower() not in seen:
            seen.add(token.lower())
            keywords.append(token)

    # 3. 词表没覆盖时，按标点和停用词切出短片段作为兜底关键词。
    if not keywords:
        cleaned = re.sub(r"\d+(?:\.\d+)?\s*[-~—到至]\s*\d+(?:\.\d+)?", " ", text or "")
        cleaned = re.sub(
            r"(?:预算|不超过)?\s*\d+(?:\.\d+)?\s*(?:元|块)?\s*(?:以内|以下|左右|之内)?",
            " ",
            cleaned,
        )
        for phrase in sorted(_STOPWORDS, key=len, reverse=True):
            cleaned = cleaned.replace(phrase, " ")
        for chunk in re.split(r"[^\u4e00-\u9fffA-Za-z0-9]+", cleaned):
            chunk = chunk.strip()
            if 2 <= len(chunk) <= 8 and chunk not in keywords:
                keywords.append(chunk)

    if category:
        keywords = [word for word in keywords if word != category]
    return keywords[:4]
