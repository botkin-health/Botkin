"""ADR-0011 п. 4: роутер берёт первый JSON-объект из ответа, а не json.loads по всему тексту.

Sonnet 5.5 и Opus 5.5 иногда пишут короткое рассуждение перед JSON
(«Plum ~46 kcal/100g … ```json {…}```»). Строгий json.loads ронял такие ответы:
на eval golden_v3 18.10.2026 — 2 из 111 у Sonnet 5.5, 9 из 111 у Opus 5.5.
Раньше это кончалось тремя ретраями и fallback на GPT-4o.
"""

from unittest.mock import MagicMock, patch

import pytest

from config.models import FOOD_TEXT_MODEL_ANTHROPIC
from core.llm.router import _extract_json_object, analyze_message_claude

PAYLOAD = (
    '{"type":"food","data":{"dish_name":"Слива","meal_type":"snack",'
    '"items":[{"name":"Слива","weight":30,"calories":14,"protein":0,"fats":0,"carbs":3}],'
    '"total_nutrition":{"calories":14,"protein":0,"fats":0,"carbs":3,"fiber":0,"has_alcohol":false,"drinks":0}}}'
)


@pytest.mark.parametrize(
    "raw",
    [
        PAYLOAD,
        f"```json\n{PAYLOAD}\n```",
        f"Plum ~46 kcal/100g, one plum ≈ 30 g.\n\n```json\n{PAYLOAD}\n```",
        f"Plum ~46 kcal/100g. {PAYLOAD}",
        f"{PAYLOAD}\n\nNote: weight is an estimate.",
    ],
)
def test_extract_first_json_object(raw):
    assert _extract_json_object(raw)["data"]["dish_name"] == "Слива"


def test_no_json_raises():
    with pytest.raises(ValueError):
        _extract_json_object("Не могу разобрать сообщение")


def _resp(blocks):
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = {"content": blocks, "usage": {}}
    return r


def test_router_accepts_reasoning_before_json_without_retry():
    resp = _resp([{"type": "text", "text": f"Plum ~46 kcal/100g.\n```json\n{PAYLOAD}\n```"}])
    with (
        patch("core.llm.router.requests.post", return_value=resp) as post,
        patch("core.llm_usage.log_anthropic_response"),
        patch("core.llm.router._known_products_block", return_value=""),
    ):
        result = analyze_message_claude(text="слива")
    assert result is not None and result["data"]["dish_name"] == "Слива"
    assert post.call_count == 1


def test_food_router_default_model_is_sonnet_5_5():
    assert FOOD_TEXT_MODEL_ANTHROPIC == "claude-sonnet-5-5"


def test_sonnet_5_5_cost_not_priced_as_sonnet_5():
    from core.llm_usage import compute_cost

    # cache_read у 5.5 — $0.10/MT, у Sonnet 5 — $0.20/MT
    assert compute_cost("claude-sonnet-5-5", 0, 0, 0, 1_000_000) == pytest.approx(0.10)
    assert compute_cost("claude-sonnet-5-5-20261001", 0, 0, 0, 1_000_000) == pytest.approx(0.10)
    assert compute_cost("claude-sonnet-5", 0, 0, 0, 1_000_000) == pytest.approx(0.20)
