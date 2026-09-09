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
    # #427: preview_message_id — MealStateData требует int; без явного значения
    # AsyncMock().message_id вернул бы Mock-объект и упал бы на валидации.
    processing_msg.message_id = 424242

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
async def test_menu_photo_without_caption_stores_photo_paths(tmp_path):
    """Regression for #256: handle_menu_photo() must write "photo_paths" (list),
    not "photo_path" (singular) — otherwise save_meal_to_db() never sees the
    photo and nutrition_log.photo_paths stays empty for this whole flow."""
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
    ):
        await process_photos_list(msg, [photo])

    st = state_manager.get_state("895655")
    assert st is not None
    assert st.data.get("photo_path") is None, "legacy singular key must not be written"
    assert st.data.get("photo_paths") == [str(photo)]


@pytest.mark.asyncio
async def test_vitamins_photo_shows_confirmation(tmp_path):
    """LLM returns type='vitamins' → confirmation keyboard shown, state saved.

    Since 5a8b910 feat(supplements): vitamins are no longer saved immediately.
    A confirmation keyboard is shown and state=waiting_supplement_confirmation is
    set. save_supplements is called only after the user taps confirm.
    """
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "vitamins",
        "data": {"items": ["Vitamin D 5000 IU", "Omega-3 1000mg"]},
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    # Confirmation message must mention supplements
    processing_msg.edit_text.assert_called_once()
    call_text = processing_msg.edit_text.call_args[0][0]
    assert "💊" in call_text or "добавк" in call_text.lower()

    # State must be waiting_supplement_confirmation with items stored
    st = state_manager.get_state("895655")
    assert st is not None
    assert st.state == "waiting_supplement_confirmation"
    assert "Vitamin D 5000 IU" in st.data.get("supplements", [])


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


# ── #436: подсказка «Нажми Сохранить» во всех превью с save/cancel ─────────


@pytest.mark.asyncio
async def test_weight_photo_confirmation_has_confirm_hint(tmp_path):
    """Прецедент #436: пользователь не понимал, что превью нужно подтвердить.
    Карточка веса с кнопками Сохранить/Отмена должна нести явную подсказку."""
    from handlers.meal_preview import CONFIRM_HINT
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

    sent_text = processing_msg.edit_text.call_args[0][0]
    assert CONFIRM_HINT in sent_text


@pytest.mark.asyncio
async def test_vitamins_photo_confirmation_has_confirm_hint(tmp_path):
    """Та же подсказка нужна для карточки добавок (SupplementConfirmationCallback)."""
    from handlers.meal_preview import CONFIRM_HINT
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message()
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "vitamins",
        "data": {"items": ["Vitamin D 5000 IU"]},
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    sent_text = processing_msg.edit_text.call_args[0][0]
    assert CONFIRM_HINT in sent_text


@pytest.mark.asyncio
async def test_menu_photo_fallback_confirmation_has_confirm_hint(tmp_path):
    """handle_menu_photo() (OCR fallback ветка) тоже строит текст вручную —
    подсказка должна быть и здесь."""
    from handlers.meal_preview import CONFIRM_HINT
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

    sent_text = processing_msg.edit_text.call_args[0][0]
    assert CONFIRM_HINT in sent_text


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
    # #427: карточка несёт свой заявленный итог — иначе process_llm_food_data
    # досчитает по ингредиентам и получит больше заявленного (764 вместо 564).
    assert result["data"]["total_nutrition"]["calories"] == 400
    assert result["data"]["totals_anchor"] == "card"


def test_build_router_result_single_component_collapses():
    """Без покомпонентной разбивки (0/1 компонент) — один item, как раньше."""
    from handlers.photo import build_router_result_from_menu_data

    menu_data = {"dish_name": "Блюдо из меню", "calories": 300, "protein": 10, "fats": 8, "carbs": 40, "weight": 200}

    result = build_router_result_from_menu_data(menu_data, caption="")

    items = result["data"]["items"]
    assert len(items) == 1
    assert items[0]["calories"] == 300
    # #427: якорь только для покомпонентной разбивки (≥2) — одиночный item
    # уже несёт верный итог напрямую, масштабировать нечего.
    assert "totals_anchor" not in result["data"]


def test_build_router_result_single_component_collapses_boundary():
    """Ровно 1 компонент (граница условия ≥2) → один item из итогов menu_data."""
    from handlers.photo import build_router_result_from_menu_data

    menu_data = {
        "dish_name": "Суп",
        "calories": 200,
        "weight": 300,
        "components": [{"name": "суп", "weight": 300, "calories": 200}],
    }

    result = build_router_result_from_menu_data(menu_data, caption="обед")

    assert len(result["data"]["items"]) == 1


def test_safe_float_rejects_inf_nan_and_garbage():
    """_safe_float: inf/nan/'много'/None → None; нормальные числа → float."""
    from handlers.photo import _safe_float

    assert _safe_float("много") is None
    assert _safe_float(None) is None
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("nan")) is None
    assert _safe_float("12.5") == 12.5
    assert _safe_float(0) == 0.0


@pytest.mark.asyncio
async def test_photo_caption_modifier_removes_component(tmp_path):
    """#427: подпись «Без кускуса» к фото-карточке убирает компонент из состава.

    Карточка на 400 ккал (3 компонента), подпись исключает «кускус» —
    итог должен уменьшиться на его долю, а превью — содержать «− Кускус».
    """
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")

    msg, processing_msg = _make_message(caption="Без кускуса")
    msg.text = None  # AsyncMock: без этого message.text.strip() возвращает coroutine
    photo = _fake_photo(tmp_path)

    llm_result = {
        "type": "food",
        "data": {
            "dish_name": "Стрипсы с кускусом и кабачком",
            "items": [
                {"name": "Куриные стрипсы", "weight": 150, "calories": 250, "protein": 30, "fats": 12, "carbs": 5},
                {"name": "Кускус", "weight": 60, "calories": 100, "protein": 3, "fats": 1, "carbs": 20},
                {"name": "Кабачок", "weight": 100, "calories": 50, "protein": 1, "fats": 1, "carbs": 5},
            ],
            "total_nutrition": {"calories": 400, "protein": 34, "fats": 14, "carbs": 30},
        },
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    st = state_manager.get_state("895655")
    assert st is not None
    assert st.state == "waiting_confirmation"
    assert all(it["product"] != "Кускус" for it in st.data["meal_items"])
    assert st.data["meal_totals"]["calories"] == pytest.approx(300, abs=1)

    # Превью печатается через processing_message.edit_text (safe_edit_text)
    preview_calls = [c for c in processing_msg.edit_text.call_args_list if c.args and "− Кускус" in c.args[0]]
    assert preview_calls, "Превью не содержит «− Кускус»"


@pytest.mark.asyncio
async def test_caption_on_card_runs_single_pass_and_keeps_anchor(tmp_path):
    """#427: фото карточки с итогом на порцию + подпись «без кускуса» → ОДИН LLM-вызов,
    итог якорится к карточке (564), кускус вычтен; раньше второй проход перезаписывал 564 → 886."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895655")
    msg, processing_msg = _make_message(caption="без кускуса")
    msg.text = None
    photo = _fake_photo(tmp_path)

    components = [
        {"name": "Куриные стрипсы", "weight": 300, "calories": 330, "protein": 36, "fats": 12, "carbs": 8},
        {"name": "Кускус", "weight": 60, "calories": 210, "protein": 7, "fats": 1, "carbs": 43},
        {"name": "Кабачок", "weight": 100, "calories": 24, "protein": 1, "fats": 0, "carbs": 5},
        {"name": "Растительное масло", "weight": 15, "calories": 135, "protein": 0, "fats": 15, "carbs": 0},
    ]
    llm_result = {
        "type": "food",
        "data": {
            "dish_name": "Куриные стрипсы с кабачком",
            "items": components,
            "total_nutrition": {"calories": 564, "protein": 43, "fats": 21, "carbs": 50},
        },
    }

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result) as mock_llm,
        patch(MENU_PARSER, return_value=None),
    ):
        await process_photos_list(msg, [photo])

    assert mock_llm.call_count == 1, "второй LLM-проход перезаписывает якорный итог"
    state = state_manager.get_state("895655")
    assert state is not None and state.state == "waiting_confirmation"
    names = [it["product"] for it in state.data["meal_items"]]
    assert "Кускус" not in names and len(names) == 3
    raw_sum = sum(c["calories"] for c in components)
    expected = 564 - 210 * 564 / raw_sum
    assert state.data["meal_totals"]["calories"] == pytest.approx(expected, abs=3)


def test_build_router_result_does_not_duplicate_caption_already_in_dish_name():
    """#427: LLM сама вписала модификатор в dish_name («…(без кускуса)») —
    build_router_result_from_menu_data не должна приклеивать его второй раз."""
    from handlers.photo import build_router_result_from_menu_data

    menu_data = {
        "dish_name": "Куриные стрипсы с кабачком и огурцом (без кускуса)",
        "calories": 564,
        "protein": 43,
        "fats": 21,
        "carbs": 50,
        "components": [
            {"name": "Куриные стрипсы", "weight": 300, "calories": 330, "protein": 36, "fats": 12, "carbs": 8},
            {"name": "Кабачок", "weight": 100, "calories": 24, "protein": 1, "fats": 0, "carbs": 5},
        ],
    }

    result = build_router_result_from_menu_data(menu_data, caption="без кускуса")

    assert result["data"]["dish_name"] == "Куриные стрипсы с кабачком и огурцом (без кускуса)"
    assert result["data"]["dish_name"].count("без кускуса") == 1
