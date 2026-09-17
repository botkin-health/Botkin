"""
Регресс: Claude Sonnet 5 на сложных/неоднозначных блюдах (бренды, несколько
позиций, дроби вроде «половина пиццы») сам включает extended thinking и
возвращает content[0] типа "thinking", а JSON-текст — только в content[1].

analyze_message_claude() читал жёстко result["content"][0]["text"], поэтому
на таких ответах падал с KeyError('text'), ретраил тот же запрос 3 раза и
улетал на fallback GPT-4o — отсюда многосекундные задержки на вводе еды.

Воспроизведено живым вызовом на проде 17.09.2026: "яблоко 150 г" -> content
=["text"], а "половина пиццы Зотман груша с горгонзолой и кофе с сахаром" ->
content=["thinking", "text"].
"""

from unittest.mock import MagicMock, patch

from core.llm.router import analyze_message_claude


def _claude_response(content_blocks, cache_read=5189):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "content": content_blocks,
        "usage": {
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": 0,
        },
    }
    return resp


def test_analyze_message_claude_skips_leading_thinking_block():
    """content[0]=thinking, content[1]=text — должен взять текстовый блок."""
    payload = (
        '{"type":"food","data":{"dish_name":"Пицца","meal_type":"lunch",'
        '"items":[{"name":"Пицца","weight":250,"quantity":"половина",'
        '"calories":650,"protein":22,"fats":30,"carbs":72,"fiber":4,"drinks":0}],'
        '"total_nutrition":{"calories":650,"protein":22,"fats":30,"carbs":72,'
        '"fiber":4,"has_alcohol":false,"drinks":0}}}'
    )
    mock_resp = _claude_response(
        [
            {"type": "thinking", "thinking": "рассуждаю о блюде...", "signature": "x"},
            {"type": "text", "text": payload},
        ]
    )

    with (
        patch("core.llm.router.requests.post", return_value=mock_resp),
        patch("core.llm_usage.log_anthropic_response"),
        patch("core.llm.router._known_products_block", return_value=""),
    ):
        result = analyze_message_claude(text="половина пиццы Зотман груша с горгонзолой и кофе с сахаром")

    assert result is not None
    assert result["type"] == "food"
    assert result["data"]["dish_name"] == "Пицца"


def test_analyze_message_claude_plain_text_block_still_works():
    """content=[text] (простые позиции без thinking) — не должен сломаться."""
    payload = '{"type":"food","data":{"dish_name":"Яблоко","meal_type":"snack","items":[],"total_nutrition":{"calories":80,"protein":0,"fats":0,"carbs":20,"fiber":2,"has_alcohol":false,"drinks":0}}}'
    mock_resp = _claude_response([{"type": "text", "text": payload}])

    with (
        patch("core.llm.router.requests.post", return_value=mock_resp),
        patch("core.llm_usage.log_anthropic_response"),
        patch("core.llm.router._known_products_block", return_value=""),
    ):
        result = analyze_message_claude(text="яблоко 150 г")

    assert result is not None
    assert result["data"]["dish_name"] == "Яблоко"
