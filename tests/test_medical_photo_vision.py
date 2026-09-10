"""
Fix 1 (photo.py + router.py, 04.09.2026): vision не читала текст с фото упаковки
лекарства — даже когда LLM реально распознала текст (SCENARIO 5.1 "medical" в
core/llm/router.py), код в handlers/photo.py выбрасывал это распознавание и
подставлял агенту фиксированную фразу «LLM-vision не распознал…». Тест проверяет,
что распознанный текст ("reply" из router_result) теперь доходит до ask_agent.

Мокаем все LLM-вызовы (analyze_message, ask_agent) — реальных запросов к моделям
не делаем.
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

# Patch targets (lazy imports inside function bodies — must patch at source)
LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
ARCHIVE_PHOTO = "handlers.doc_upload.archive_photo_as_document"


def _make_photo_message(user_id: int, caption: str):
    processing_msg = AsyncMock()
    processing_msg.edit_text = AsyncMock()

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.caption = caption
    msg.text = None
    msg.photo = [MagicMock(file_id="fake_file_id")]
    msg.answer = AsyncMock(return_value=processing_msg)
    msg.bot = AsyncMock()
    return msg, processing_msg


@pytest.mark.asyncio
async def test_medical_photo_reply_forwarded_to_agent(tmp_path):
    """Router возвращает type='medical' с непустым data.reply (SCENARIO 5.1) —
    код должен передать РАСПОЗНАННЫЙ ТЕКСТ агенту, а не фиксированную фразу
    «LLM-vision не распознал…»."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895655"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "photo.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    caption = "у тебя есть данные по этому препарату?"
    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption=caption,
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), caption)

    recognized_text = "На фото упаковка «Омник», действующее вещество тамсулозин, дозировка 0.4 мг."
    medical_result = {"type": "medical", "data": {"subtype": "medication_package", "reply": recognized_text}}

    mock_ask_agent = MagicMock(return_value="Да, есть данные — Омник (тамсулозин) применяется при аденоме простаты.")

    with (
        patch(LLM_ANALYZE, return_value=medical_result),
        patch(ARCHIVE_PHOTO, return_value="archived.jpg"),
        patch(ASK_AGENT, mock_ask_agent),
    ):
        await handle_description(msg, description=None, processing_message=processing_msg)

    assert mock_ask_agent.called, "ask_agent должен был быть вызван для нераспознанного как food/vitamins/bp фото"
    call_args = mock_ask_agent.call_args.args
    prompt_sent_to_agent = call_args[1]

    # Распознанный текст ДОЛЖЕН попасть в промпт агента
    assert "тамсулозин" in prompt_sent_to_agent or "Омник" in prompt_sent_to_agent
    # Старая фиксированная фраза-заглушка НЕ должна маскировать реально распознанный текст
    assert "не распознал на фото еду" not in prompt_sent_to_agent


@pytest.mark.asyncio
async def test_medical_photo_without_reply_keeps_stock_message(tmp_path):
    """Если router вернул type='other'/'medical' БЕЗ reply (вообще ничего не разобрал) —
    код по-прежнему честно говорит агенту, что vision не распознала фото (регресс-guard,
    чтобы фикс не начал выдумывать несуществующий reply)."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895656"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "photo2.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    caption = "что это?"
    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption=caption,
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), caption)

    other_result = {"type": "other", "data": {"reply": ""}}
    mock_ask_agent = MagicMock(return_value="Не могу понять, что на фото — опиши текстом.")

    with (
        patch(LLM_ANALYZE, return_value=other_result),
        patch(ARCHIVE_PHOTO, return_value="archived.jpg"),
        patch(ASK_AGENT, mock_ask_agent),
    ):
        await handle_description(msg, description=None, processing_message=processing_msg)

    assert mock_ask_agent.called
    prompt_sent_to_agent = mock_ask_agent.call_args.args[1]
    assert "не распознал на фото еду" in prompt_sent_to_agent


# ── issue #439: медицинский документ без /doc → run_doc_pipeline ────────────

RUN_DOC_PIPELINE = "handlers.doc_upload.run_doc_pipeline"


@pytest.mark.asyncio
async def test_medical_lab_report_with_reply_routes_to_doc_pipeline(tmp_path):
    """type='medical', subtype='lab_report', reply НЕПУСТОЙ (это контрактное
    поведение router.py — reply у medical всегда есть) + FSMContext доступен →
    вместо тихого архива запускаем run_doc_pipeline (issue #439), как если бы
    юзер прислал /doc. Раньше код ошибочно ждал ПУСТОЙ reply для этого случая,
    который на практике не бывает — фото анализа уходило в stock fallback."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895700"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)
    fsm_state = AsyncMock()

    medical_lab_report = {
        "type": "medical",
        "data": {"subtype": "lab_report", "reply": "На фото бланк анализа крови с показателями."},
    }
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")

    with (
        patch(LLM_ANALYZE, return_value=medical_lab_report),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
    ):
        await handle_description(
            msg, description="это анализ, что скажешь?", processing_message=processing_msg, state=fsm_state
        )

    assert mock_run_pipeline.called, "run_doc_pipeline должен был быть вызван вместо архивации"
    assert not mock_archive.called, "archive_photo_as_document НЕ должен вызываться, если пошли doc-пайплайном"
    call_kwargs = mock_run_pipeline.call_args.kwargs
    assert call_kwargs["is_pdf"] is False
    assert call_kwargs["content"] == fake_photo_path.read_bytes()


@pytest.mark.asyncio
async def test_medical_doctor_note_routes_to_doc_pipeline(tmp_path):
    """type='medical', subtype='doctor_note' → тоже doc-пайплайн."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895703"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc4.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)
    fsm_state = AsyncMock()

    medical_doctor_note = {
        "type": "medical",
        "data": {"subtype": "doctor_note", "reply": "На фото заключение врача."},
    }
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")

    with (
        patch(LLM_ANALYZE, return_value=medical_doctor_note),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
    ):
        await handle_description(
            msg, description="что скажешь по заключению?", processing_message=processing_msg, state=fsm_state
        )

    assert mock_run_pipeline.called
    assert not mock_archive.called


@pytest.mark.asyncio
async def test_medical_without_subtype_routes_to_doc_pipeline(tmp_path):
    """type='medical' без subtype (LLM забыл его выставить) — тоже считаем
    документом и ведём в doc-пайплайн (безопасный дефолт: пайплайн сам покажет
    «ничего не нашёл» с опцией архивации)."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895704"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc5.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)
    fsm_state = AsyncMock()

    medical_no_subtype = {"type": "medical", "data": {"reply": "На фото похоже на медицинский документ."}}
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")

    with (
        patch(LLM_ANALYZE, return_value=medical_no_subtype),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
    ):
        await handle_description(msg, description="что это?", processing_message=processing_msg, state=fsm_state)

    assert mock_run_pipeline.called
    assert not mock_archive.called


@pytest.mark.asyncio
async def test_other_type_keeps_old_archive_behavior(tmp_path):
    """type='other' без caption — issue #439 намеренно НЕ трогает этот случай
    (иначе скриншоты Garmin и случайные фото получают document-превью вместо
    диалога с агентом). Старое поведение сохраняется: run_doc_pipeline НЕ
    вызывается, фото архивируется, без caption/reply — stock-сообщение."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895701"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc2.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)
    fsm_state = AsyncMock()

    other_no_caption = {"type": "other", "data": {"reply": ""}}
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")

    with (
        patch(LLM_ANALYZE, return_value=other_no_caption),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
    ):
        await handle_description(msg, description="глянь что там", processing_message=processing_msg, state=fsm_state)

    assert not mock_run_pipeline.called, "type='other' НЕ должен вести в doc-пайплайн"
    assert mock_archive.called, "type='other' должен по-прежнему архивироваться как раньше"


@pytest.mark.asyncio
async def test_medical_lab_report_falls_back_to_archive_when_no_state(tmp_path):
    """Регресс-guard: старые вызовы handle_description без FSMContext (state=None)
    ведут себя как раньше — архивируют фото, doc-пайплайн не заводят (у него
    просто нет FSMContext, чтобы поставить DocUpload.waiting)."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895702"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc3.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)

    medical_lab_report = {
        "type": "medical",
        "data": {"subtype": "lab_report", "reply": "На фото бланк анализа крови."},
    }
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")
    mock_ask_agent = MagicMock(return_value="ответ агента")

    with (
        patch(LLM_ANALYZE, return_value=medical_lab_report),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
        patch(ASK_AGENT, mock_ask_agent),
    ):
        await handle_description(
            msg, description="это анализ, что скажешь?", processing_message=processing_msg, state=None
        )

    assert not mock_run_pipeline.called
    assert mock_archive.called


@pytest.mark.asyncio
async def test_medical_photo_routes_with_processing_msg_and_question(tmp_path):
    """Issue #441 п.4/п.6: run_doc_pipeline из handle_description должен получить
    processing_msg=processing_message (переиспользовать уже показанное «🤔 думаю...»
    вместо второго сообщения) и question=<то, что пользователь реально написал/
    сказал>, а не только message.caption с фото (которого тут вообще нет)."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    user_id = "895705"
    state_manager.clear_state(user_id)

    fake_photo_path = tmp_path / "doc6.jpg"
    fake_photo_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    state = create_photo_state(
        user_id=user_id,
        photo_paths=[fake_photo_path],
        photo_file_ids=["fake_file_id"],
        caption="",
    )
    state_manager.set_state(user_id, state)

    msg, processing_msg = _make_photo_message(int(user_id), None)
    fsm_state = AsyncMock()

    medical_lab_report = {
        "type": "medical",
        "data": {"subtype": "lab_report", "reply": "На фото бланк анализа крови."},
    }
    mock_run_pipeline = AsyncMock()
    mock_archive = MagicMock(return_value="archived.jpg")
    user_typed_question = "это нормально?"

    with (
        patch(LLM_ANALYZE, return_value=medical_lab_report),
        patch(ARCHIVE_PHOTO, mock_archive),
        patch(RUN_DOC_PIPELINE, mock_run_pipeline),
    ):
        await handle_description(
            msg, description=user_typed_question, processing_message=processing_msg, state=fsm_state
        )

    assert mock_run_pipeline.called
    call_kwargs = mock_run_pipeline.call_args.kwargs
    assert call_kwargs["processing_msg"] is processing_msg
    assert call_kwargs["auto"] is True
    assert user_typed_question in (call_kwargs.get("question") or "")
