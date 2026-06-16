"""
Smoke tests for telegram-bot/handlers/photo.py

Each test targets one main branch of process_photos_list().
No real Telegram connection, no OpenAI API.

Patch strategy:
  - parse_weight_screenshot  → lazy import inside fn → patch at source module
  - analyze_message          → lazy import inside fn → patch at source module
  - parse_menu_photo         → top-level import (line 34) → patch on handlers.photo
  - save_supplements         → lazy import inside fn → patch at source module
  - save_weight_to_db        → lazy import inside fn → patch at source module
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── project root on sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_message(user_id: int = 895655, caption: str | None = None):
    """Return (message_mock, processing_msg_mock)."""
    processing_msg = AsyncMock()
    processing_msg.edit_text = AsyncMock()

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.caption = caption
    msg.photo = [MagicMock(file_id="fake_file_id")]
    msg.media_group_id = None
    msg.answer = AsyncMock(return_value=processing_msg)
    msg.bot = AsyncMock()
    return msg, processing_msg


def _fake_photo(tmp_path: Path, name: str = "photo.jpg") -> Path:
    """Create a minimal placeholder file that looks like a photo."""
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # JPEG magic bytes
    return p


# Patch targets ---------------------------------------------------------------
# lazy imports (inside function bodies) must be patched at source, not on handlers.photo
OCR_WEIGHT = "core.vision.ocr_weight.parse_weight_screenshot"
LLM_ANALYZE = "core.llm.router.analyze_message"
SAVE_SUPPS = "core.health.supplements.save_supplements"
SAVE_WEIGHT = "helpers.db_save.save_weight_to_db"
# top-level import → patched on the module that imported it
MENU_PARSER = "handlers.photo.parse_menu_photo"


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weight_photo_shows_confirmation(tmp_path):
    """parse_weight_screenshot returns a weight → bot sends confirmation + keyboard."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    weight_data = {"weight": 82.5, "date": "2026-04-20", "body_fat": None}

    with (
        patch(OCR_WEIGHT, return_value=weight_data),
        patch(LLM_ANALYZE, return_value=None),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    # Weight confirmation must appear (edit_text or second answer)
    assert processing_msg.edit_text.called or msg.answer.call_count >= 2

    # State must record weights
    st = state_manager.get_state("895655")
    assert st is not None
    assert st.state == "waiting_weight_confirmation"
    assert st.data["weights"][0]["weight"] == 82.5


@pytest.mark.asyncio
async def test_food_llm_response_triggers_menu_flow(tmp_path):
    """LLM returns type='food' with calories → food/menu flow starts (no crash)."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message(caption=None)
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "food",
        "data": {
            "dish_name": "Гречка с курицей",
            "items": [
                {"name": "Гречка с курицей", "weight": 300, "calories": 350, "protein": 25, "fats": 8, "carbs": 45}
            ],
            "total_nutrition": {"calories": 350, "protein": 25, "fats": 8, "carbs": 45},
        },
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
        # handle_menu_photo writes state — allow it
    ):
        await process_photos_list(msg, [photo])

    # Processing message must have been sent at minimum
    msg.answer.assert_called()


@pytest.mark.asyncio
async def test_vitamins_photo_calls_save_supplements(tmp_path):
    """LLM returns type='vitamins' → save_supplements is called, confirmation shown."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "vitamins",
        "data": {"items": ["Vitamin D 5000 IU", "Omega-3 1000mg"]},
    }

    mock_save = MagicMock(return_value=True)

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
        patch(SAVE_SUPPS, mock_save),
    ):
        await process_photos_list(msg, [photo])

    mock_save.assert_called_once()
    processing_msg.edit_text.assert_called_once()
    call_text = processing_msg.edit_text.call_args[0][0]
    assert "💊" in call_text or "витамин" in call_text.lower()


@pytest.mark.asyncio
async def test_weight_from_llm_saves_and_confirms(tmp_path):
    """LLM returns type='weight' → save_weight_to_db called, confirmation shown."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "weight",
        "data": {"weight": 83.1, "date": "2026-04-20"},
    }

    mock_save_w = MagicMock(return_value=True)

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
        patch(SAVE_WEIGHT, mock_save_w),
    ):
        await process_photos_list(msg, [photo])

    mock_save_w.assert_called_once()
    processing_msg.edit_text.assert_called_once()
    call_text = processing_msg.edit_text.call_args[0][0]
    assert "83.1" in call_text


@pytest.mark.asyncio
async def test_parse_menu_photo_fallback(tmp_path):
    """LLM returns None → parse_menu_photo fallback triggers menu flow (no crash)."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    menu_result = {
        "dish_name": "Борщ",
        "calories": 250,
        "protein": 8,
        "fats": 10,
        "carbs": 30,
        "weight": 300,
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=None),
        patch(MENU_PARSER, return_value=menu_result),
    ):
        await process_photos_list(msg, [photo])

    msg.answer.assert_called()


@pytest.mark.asyncio
async def test_no_recognition_asks_for_description(tmp_path):
    """Nothing recognised → bot edits processing_msg with "not food" prompt.

    FIX 26.05.2026: when LLM returns None (network/limit error) or photo is not food,
    we no longer set waiting_description state. Instead we show a neutral prompt
    so the user can respond with text (which goes through normal routing).
    This prevents Garmin screenshots and other non-food photos from getting stuck
    in the food flow.
    """
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message(caption=None)
    photo = _fake_photo(tmp_path)

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=None),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    # Bot must send some response (not silent)
    assert processing_msg.edit_text.called
    call_text = processing_msg.edit_text.call_args[0][0]
    # Should mention photo or how to retry
    assert "фото" in call_text.lower() or "текст" in call_text.lower()

    # State must NOT be waiting_description — unrecognized photos should not
    # trap the user in the food flow (see fix 26.05.2026 in photo.py)
    st = state_manager.get_state("895655")
    assert st is None or st.state != "waiting_description"


@pytest.mark.asyncio
async def test_save_photo_failure_returns_none():
    """If bot.get_file raises, save_photo() must return None without crashing."""
    from handlers.photo import save_photo

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 895655
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(side_effect=Exception("Telegram API error"))

    result = await save_photo(msg, "fake_file_id")
    assert result is None


@pytest.mark.asyncio
async def test_llm_exception_falls_back_to_parse_menu_photo(tmp_path):
    """analyze_message raises → exception caught, parse_menu_photo fallback, no crash."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    menu_result = {
        "dish_name": "Плов",
        "calories": 400,
        "protein": 15,
        "fats": 18,
        "carbs": 50,
        "weight": 350,
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, side_effect=RuntimeError("LLM timeout")),
        patch(MENU_PARSER, return_value=menu_result),
    ):
        await process_photos_list(msg, [photo])

    msg.answer.assert_called()


@pytest.mark.asyncio
async def test_multiple_photos_with_one_weight(tmp_path):
    """
    Album: one weight photo + one food photo.
    Weight confirmation is sent as a separate message; food flow continues for the other.
    """
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    weight_photo = _fake_photo(tmp_path, "weight.jpg")
    food_photo = _fake_photo(tmp_path, "food.jpg")

    weight_data = {"weight": 81.0, "date": "2026-04-20"}

    def ocr_side_effect(paths, api_key, description=""):
        if weight_photo in paths:
            return weight_data
        return None

    llm_food = {
        "type": "food",
        "data": {
            "dish_name": "Яйца с тостом",
            "items": [
                {"name": "Яйца с тостом", "weight": 150, "calories": 300, "protein": 15, "fats": 12, "carbs": 25}
            ],
            "total_nutrition": {"calories": 300, "protein": 15, "fats": 12, "carbs": 25},
        },
    }

    with (
        patch(OCR_WEIGHT, side_effect=ocr_side_effect),
        patch(LLM_ANALYZE, return_value=llm_food),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [weight_photo, food_photo])

    # Weight confirmation + food answer → at least 2 answer calls
    assert msg.answer.call_count >= 2


# ── Issue #115: приоритет фото-декомпозиции над текстовой подписью ────────────
def test_build_router_result_keeps_multiple_components():
    """При фото с ≥2 компонентами подпись НЕ схлопывает блюдо в один item."""
    from handlers.photo import build_router_result_from_menu_data

    menu_data = {
        "dish_name": "Боул",
        "calories": 400,
        "protein": 20,
        "fats": 15,
        "carbs": 40,
        "weight": 320,
        "components": [
            {"name": "зелень", "weight": 120, "calories": 60, "protein": 3, "fats": 1, "carbs": 8},
            {"name": "лосось", "weight": 100, "calories": 200, "protein": 17, "fats": 12, "carbs": 0},
            {"name": "заправка лимонная", "weight": 30, "calories": 140, "protein": 0, "fats": 15, "carbs": 1},
        ],
    }

    result = build_router_result_from_menu_data(menu_data, caption="Обед: салат зелёный с лимонной заправкой")

    items = result["data"]["items"]
    assert len(items) == 3
    names = {i["name"] for i in items}
    assert names == {"зелень", "лосось", "заправка лимонная"}
    # Подпись используется как уточнение названия блюда, не как единственный item.
    assert "салат зелёный с лимонной заправкой" in result["data"]["dish_name"]


def test_build_router_result_single_component_collapses():
    """Без покомпонентной разбивки (0/1 компонент) — один item, как раньше."""
    from handlers.photo import build_router_result_from_menu_data

    menu_data = {"dish_name": "Блюдо из меню", "calories": 300, "protein": 10, "fats": 8, "carbs": 40, "weight": 200}

    result = build_router_result_from_menu_data(menu_data, caption="")

    items = result["data"]["items"]
    assert len(items) == 1
    assert items[0]["calories"] == 300
