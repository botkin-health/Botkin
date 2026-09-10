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


# ── issue #439: PDF с текстом без /doc — эвристика → doc-пайплайн ───────────


def _make_pdf_document_message(user_id: int = 895800, file_name: str = "analysis.pdf"):
    """Сообщение с document=PDF (без caption). Возвращает (message_mock, processing_msg_mock)."""
    doc = MagicMock()
    doc.mime_type = "application/pdf"
    doc.file_name = file_name

    processing_msg = AsyncMock()
    processing_msg.edit_text = AsyncMock()
    processing_msg.delete = AsyncMock()

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.document = doc
    msg.caption = None
    msg.media_group_id = None
    msg.answer = AsyncMock(return_value=processing_msg)
    return msg, processing_msg


@pytest.mark.asyncio
async def test_pdf_with_lab_markers_routes_to_doc_pipeline(tmp_path):
    """PDF с текстом, похожим на анализ (единицы, «референсные», «заключение») —
    вместо ask_agent запускаем run_doc_pipeline (issue #439), чтобы показатели
    попали в blood_tests/профиль, а не потерялись в пересказе агента."""
    from handlers.photo import handle_document_image

    msg, processing_msg = _make_pdf_document_message()
    fake_pdf_path = tmp_path / "analysis.pdf"
    fake_pdf_path.write_bytes(b"%PDF-fake-content")

    lab_text = (
        "Общий анализ крови. Гемоглобин 140 г/л. Лейкоциты 6.1 10^9/л. "
        "Референсные значения указаны в графе норма. Заключение: без отклонений."
    )
    mock_run_pipeline = AsyncMock()
    mock_ask_agent = MagicMock(return_value="не должно вызываться")
    fsm_state = AsyncMock()

    with (
        patch("handlers.photo._download_pdf", AsyncMock(return_value=fake_pdf_path)),
        patch("handlers.photo._extract_pdf_text", return_value=lab_text),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
        patch("core.agent_chat.ask_agent", mock_ask_agent),
    ):
        await handle_document_image(msg, album=None, state=fsm_state)

    assert mock_run_pipeline.called, "run_doc_pipeline должен был быть вызван для PDF-анализа"
    assert not mock_ask_agent.called, "ask_agent НЕ должен вызываться, если пошли doc-пайплайном"
    call_kwargs = mock_run_pipeline.call_args.kwargs
    assert call_kwargs["is_pdf"] is True
    assert call_kwargs["ext"] == ".pdf"
    assert call_kwargs["content"] == fake_pdf_path.read_bytes()


@pytest.mark.asyncio
async def test_pdf_without_lab_markers_uses_agent_as_before(tmp_path):
    """Регресс-guard: обычный текстовый PDF (не анализ) по-прежнему идёт в
    ask_agent, как до issue #439 — эвристика не должна ловить всё подряд."""
    from handlers.photo import handle_document_image

    msg, processing_msg = _make_pdf_document_message(user_id=895801, file_name="contract.pdf")
    fake_pdf_path = tmp_path / "contract.pdf"
    fake_pdf_path.write_bytes(b"%PDF-fake-content")

    plain_text = (
        "Договор аренды офисного помещения. Стороны согласовали срок действия "
        "договора, порядок оплаты и условия расторжения."
    )
    mock_run_pipeline = AsyncMock()
    mock_ask_agent = MagicMock(return_value="Это договор аренды офиса.")

    with (
        patch("handlers.photo._download_pdf", AsyncMock(return_value=fake_pdf_path)),
        patch("handlers.photo._extract_pdf_text", return_value=plain_text),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
        patch("core.agent_chat.ask_agent", mock_ask_agent),
    ):
        await handle_document_image(msg, album=None, state=AsyncMock())

    assert not mock_run_pipeline.called
    assert mock_ask_agent.called
    processing_msg.edit_text.assert_any_call("Это договор аренды офиса.", parse_mode="HTML")


@pytest.mark.asyncio
async def test_album_of_two_medical_pdfs_asks_to_send_one_by_one(tmp_path):
    """Issue #441 п.3: альбом из ДВУХ PDF, оба похожи на анализ — раньше цикл
    обрабатывал их независимо, заводя run_doc_pipeline на каждый и затирая
    pending одного pending'ом другого в общем FSM-state юзера. Теперь — как в
    process_photos_list/doc_received: просим прислать по одному, НЕ запуская
    run_doc_pipeline ни для одного из файлов."""
    from handlers.photo import handle_document_image

    lab_text = (
        "Общий анализ крови. Гемоглобин 140 г/л. Лейкоциты 6.1 10^9/л. "
        "Референсные значения указаны в графе норма. Заключение: без отклонений."
    )

    def _make_pdf_msg(name: str):
        doc = MagicMock()
        doc.mime_type = "application/pdf"
        doc.file_name = name
        m = AsyncMock()
        m.from_user = MagicMock()
        m.from_user.id = 895810
        m.document = doc
        m.caption = None
        m.media_group_id = "album1"
        return m

    msg1 = _make_pdf_msg("analysis1.pdf")
    msg2 = _make_pdf_msg("analysis2.pdf")
    msg1.answer = AsyncMock()

    pdf_path1 = tmp_path / "analysis1.pdf"
    pdf_path1.write_bytes(b"%PDF-1")
    pdf_path2 = tmp_path / "analysis2.pdf"
    pdf_path2.write_bytes(b"%PDF-2")

    async def fake_download(msg):
        return pdf_path1 if msg is msg1 else pdf_path2

    mock_run_pipeline = AsyncMock()
    fsm_state = AsyncMock()

    with (
        patch("handlers.photo._download_pdf", side_effect=fake_download),
        patch("handlers.photo._extract_pdf_text", return_value=lab_text),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await handle_document_image(msg1, album=[msg1, msg2], state=fsm_state)

    assert not mock_run_pipeline.called, "run_doc_pipeline не должен запускаться по файлам альбома"
    msg1.answer.assert_called_once()
    reply_text = msg1.answer.call_args[0][0]
    assert "по одному" in reply_text.lower()


# ── issue #439 (gap fix): фото анализа БЕЗ подписи и БЕЗ /doc ───────────────
# Главный пропущенный случай: process_photos_list() показывала stock-текст
# «не распознал еду» и на этом всё заканчивалось — фото лабораторного анализа
# без подписи никогда не доходило ни до /doc, ни до handle_description
# (который заводит doc-пайплайн, но требует caption).


@pytest.mark.asyncio
async def test_photo_without_caption_medical_lab_report_routes_to_doc_pipeline(tmp_path):
    """type='medical', subtype='lab_report', reply НЕПУСТОЙ (контрактное
    поведение router.py — reply у medical всегда непустой) и без caption —
    раньше (ошибочно ожидая пустой reply) уходило в stock-текст «не распознал
    еду». Теперь должно вести в run_doc_pipeline, как /doc."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895900")

    msg, processing_msg = _make_message(user_id=895900, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    medical_result = {
        "type": "medical",
        "data": {"subtype": "lab_report", "reply": "На фото бланк анализа крови с показателями."},
    }
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=medical_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert mock_run_pipeline.called, "run_doc_pipeline должен был быть вызван для фото-анализа без подписи"
    call_kwargs = mock_run_pipeline.call_args.kwargs
    assert call_kwargs["is_pdf"] is False
    assert call_kwargs["content"] == photo.read_bytes()

    # Старый stock-текст «не распознал еду» НЕ должен был уйти
    for call in processing_msg.edit_text.call_args_list:
        args = call.args or ()
        assert not (args and "не распознал еду" in args[0])
    for call in msg.answer.call_args_list:
        args = call.args or ()
        assert not (args and "не распознал еду" in args[0])


@pytest.mark.asyncio
async def test_photo_without_caption_medical_doctor_note_routes_to_doc_pipeline(tmp_path):
    """type='medical', subtype='doctor_note' и без caption — тоже doc-пайплайн."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895905")

    msg, processing_msg = _make_message(user_id=895905, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    medical_result = {
        "type": "medical",
        "data": {"subtype": "doctor_note", "reply": "На фото заключение врача."},
    }
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=medical_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert mock_run_pipeline.called


@pytest.mark.asyncio
async def test_photo_without_caption_medical_no_subtype_routes_to_doc_pipeline(tmp_path):
    """type='medical' без subtype (LLM забыл выставить) — безопасный дефолт:
    тоже считаем документом и ведём в doc-пайплайн."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895906")

    msg, processing_msg = _make_message(user_id=895906, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    medical_result = {"type": "medical", "data": {"reply": "Похоже на медицинский документ."}}
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=medical_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert mock_run_pipeline.called


@pytest.mark.asyncio
async def test_photo_without_caption_medication_package_keeps_old_behavior(tmp_path):
    """type='medical', subtype='medication_package' — это упаковка лекарства
    (SCENARIO 5.1), не документ. Старое поведение (stock-текст «не распознал
    еду», агентский путь со snapshot vision-текста) должно сохраниться,
    run_doc_pipeline НЕ должен вызываться."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895901")

    msg, processing_msg = _make_message(user_id=895901, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    medical_result = {
        "type": "medical",
        "data": {"subtype": "medication_package", "reply": "На фото упаковка «Омник», тамсулозин 0.4 мг."},
    }
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=medical_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert not mock_run_pipeline.called
    processing_msg.edit_text.assert_any_call(
        "📎 Фото получил, но не распознал еду.\n\n"
        "Если это <b>анализы, документ или медданные</b> — "
        "напиши текстом что хочешь узнать, и я разберу результаты.\n\n"
        "Если это <b>еда</b> — пришли фото ещё раз с подписью "
        "(название блюда, компоненты, вес).",
        parse_mode="HTML",
    )


@pytest.mark.asyncio
async def test_photo_without_caption_food_unchanged(tmp_path):
    """Регресс-guard: фото еды без подписи по-прежнему идёт в обычный food-flow,
    run_doc_pipeline не вызывается."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895902")

    msg, processing_msg = _make_message(user_id=895902, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    llm_result = {
        "type": "food",
        "data": {
            "dish_name": "Омлет",
            "items": [{"name": "Омлет", "weight": 200, "calories": 250, "protein": 18, "fats": 15, "carbs": 4}],
            "total_nutrition": {"calories": 250, "protein": 18, "fats": 15, "carbs": 4},
        },
    }
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=llm_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert not mock_run_pipeline.called
    msg.answer.assert_called()


@pytest.mark.asyncio
async def test_photo_without_caption_other_type_keeps_old_stock_behavior(tmp_path):
    """type='other' (скриншот Гармин, случайное фото) — намеренно НЕ трогаем
    (issue #439 план явно исключает 'other', иначе каждый скриншот получал бы
    document-превью). run_doc_pipeline не вызывается, показывается старый
    stock-текст «не распознал еду»."""
    from handlers.photo import process_photos_list
    from services.state import state_manager

    state_manager.clear_state("895907")

    msg, processing_msg = _make_message(user_id=895907, caption=None)
    photo = _fake_photo(tmp_path)
    fsm_state = AsyncMock()

    other_result = {"type": "other", "data": {"reply": ""}}
    mock_run_pipeline = AsyncMock()

    with (
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=other_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await process_photos_list(msg, [photo], state=fsm_state)

    assert not mock_run_pipeline.called
    processing_msg.edit_text.assert_any_call(
        "📎 Фото получил, но не распознал еду.\n\n"
        "Если это <b>анализы, документ или медданные</b> — "
        "напиши текстом что хочешь узнать, и я разберу результаты.\n\n"
        "Если это <b>еда</b> — пришли фото ещё раз с подписью "
        "(название блюда, компоненты, вес).",
        parse_mode="HTML",
    )


@pytest.mark.asyncio
async def test_scanned_pdf_without_caption_routes_to_doc_pipeline(tmp_path):
    """Сканированный PDF (без извлекаемого текста), присланный без /doc и без
    caption: handle_document_image конвертирует страницы в изображения и
    передаёт в process_photos_list — тот должен довести их до run_doc_pipeline,
    как обычное фото-документ. Vision распознала это как медицинский документ
    (type='medical'), но не выставила subtype — безопасный дефолт всё равно
    ведёт в doc-пайплайн (в отличие от type='other', который туда не ведём)."""
    from handlers.photo import handle_document_image

    doc = MagicMock()
    doc.mime_type = "application/pdf"
    doc.file_name = "scan.pdf"

    processing_msg = AsyncMock()
    processing_msg.edit_text = AsyncMock()
    processing_msg.delete = AsyncMock()

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 895903
    msg.document = doc
    msg.caption = None
    msg.media_group_id = None
    msg.answer = AsyncMock(return_value=processing_msg)

    fake_pdf_path = tmp_path / "scan.pdf"
    fake_pdf_path.write_bytes(b"%PDF-fake-content")

    page_path = tmp_path / "scan_p1.png"
    page_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    fsm_state = AsyncMock()
    medical_no_subtype_result = {"type": "medical", "data": {"reply": "Похоже на медицинский документ."}}
    mock_run_pipeline = AsyncMock()

    with (
        patch("handlers.photo._download_pdf", AsyncMock(return_value=fake_pdf_path)),
        patch("handlers.photo._extract_pdf_text", return_value=""),  # сканированный — текста нет
        patch("handlers.photo._pdf_to_images", return_value=[page_path]),
        patch(OCR_WEIGHT, return_value=None),
        patch(LLM_ANALYZE, return_value=medical_no_subtype_result),
        patch(MENU_PARSER, return_value=None),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
    ):
        await handle_document_image(msg, album=None, state=fsm_state)

    assert mock_run_pipeline.called, "Сканированный PDF без подписи должен был дойти до run_doc_pipeline"
    call_kwargs = mock_run_pipeline.call_args.kwargs
    assert call_kwargs["is_pdf"] is False
    assert call_kwargs["content"] == page_path.read_bytes()


# ── #427: текстовая правка (модификаторы) фото-карточки до подтверждения ────


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
