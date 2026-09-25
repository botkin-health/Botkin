# tests/test_doc_upload_handler.py
import json
import re
import time

import pytest
from aiogram.exceptions import TelegramBadRequest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_message(text=None, document=None, photo=None, from_id=12345, chat_id=12345):
    msg = MagicMock()
    msg.from_user.id = from_id
    msg.chat.id = chat_id
    msg.text = text
    msg.document = document
    msg.photo = photo
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def _make_message_with_processing(caption=None, from_id=12345):
    """Сообщение чей .answer(...) возвращает mock с awaitable .edit_text — как
    доступно в run_doc_pipeline (processing = await message.answer(...))."""
    processing = AsyncMock()
    processing.edit_text = AsyncMock()

    msg = MagicMock()
    msg.from_user.id = from_id
    msg.caption = caption
    msg.answer = AsyncMock(return_value=processing)
    return msg, processing


def test_preview_text_with_values():
    """Превью содержит найденные значения."""
    from handlers.doc_upload import _preview_text

    extracted = {
        "date": "2026-04-13",
        "laboratory": "KDL",
        "values": {"Hb": "165 г/л", "ferritin": "112 нг/мл"},
    }
    text = _preview_text(extracted)
    assert "2026-04-13" in text
    assert "KDL" in text
    assert "Hb" in text
    assert "165" in text


def test_preview_text_empty_extracted():
    """Превью для пустого extracted сообщает что числа не найдены."""
    from handlers.doc_upload import _preview_text

    text = _preview_text({})
    assert "не нашёл" in text.lower() or "не найд" in text.lower() or "архив" in text.lower()


def test_preview_text_unverified_labels_gets_honest_message():
    """Issue #509: если doc_extractor отбросил все значения (названия не

    подтвердились текстом документа), превью должно честно сказать «текст
    читается плохо», а не общее «не нашёл данных» — пользователю нужно понимать,
    что числа в документе БЫЛИ, просто бот не смог надёжно связать их с названием."""
    from handlers.doc_upload import _preview_text

    extracted = {
        "date": "2026-09-20",
        "values": {},
        "_unverified_labels": ["glucose", "insulin", "HbA1c", "cholesterol_total", "HDL"],
    }
    text = _preview_text(extracted)
    assert "плохо" in text.lower()
    assert "архив" in text.lower()
    # Не должно показывать выдуманные значения — их там просто нет.
    assert "glucose" not in text.lower()


def test_preview_text_values_only_no_date():
    """Если date отсутствует — превью не падает."""
    from handlers.doc_upload import _preview_text

    extracted = {"values": {"ALT": "24 Ед/л"}}
    text = _preview_text(extracted)
    assert "ALT" in text
    assert "24" in text


def test_stored_name_format_and_deterministic():
    """Имя файла: ГГГГ-ММ-ДД_<8hex>.<ext>, детерминировано от содержимого."""
    from handlers.doc_upload import _stored_name

    name1 = _stored_name(b"same-content", ".pdf")
    name2 = _stored_name(b"same-content", ".pdf")
    assert name1 == name2  # детерминировано
    assert name1.endswith(".pdf")
    stem = name1[:-4]
    date_part, hash_part = stem.rsplit("_", 1)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", date_part)
    assert len(hash_part) == 8


def test_stored_name_different_content():
    """Разное содержимое → разные имена."""
    from handlers.doc_upload import _stored_name

    assert _stored_name(b"aaa", ".pdf") != _stored_name(b"bbb", ".pdf")


def test_append_document_to_kb_creates_file(tmp_path, monkeypatch):
    """Если kb файла нет — создаёт его с документом."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    entry = {
        "added_at": "2026-06-28",
        "file": "2026-06-28_abc12345.pdf",
        "extracted": {"values": {"Hb": "165 г/л"}},
        "user_confirmed": True,
    }
    mod.append_document_to_kb(12345, entry)

    kb_path = tmp_path / "data" / "kb" / "kb_12345.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(data["documents"]) == 1
    assert data["documents"][0]["file"] == "2026-06-28_abc12345.pdf"


def test_append_document_to_kb_preserves_sections(tmp_path, monkeypatch):
    """blood_tests и другие секции KB не трогаются."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb_999.json").write_text(
        json.dumps({"blood_tests": [{"date": "2025-01-01"}], "documents": []}),
        encoding="utf-8",
    )
    mod.append_document_to_kb(
        999,
        {"file": "x.pdf", "extracted": {}, "user_confirmed": True, "added_at": "2026-06-28"},
    )

    data = json.loads((kb_dir / "kb_999.json").read_text(encoding="utf-8"))
    assert len(data["blood_tests"]) == 1
    assert len(data["documents"]) == 1


def test_archive_photo_as_document_saves_file_and_kb_entry(tmp_path, monkeypatch):
    """Фото сохраняется в uploads/ и попадает в documents[] с auto_archived=True.

    Issue #370: пользователь прислал фото документа (не еда/анализ), раньше
    оно просто терялось. Теперь сохраняется без действий пользователя.
    """
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    photo_path = tmp_path / "incoming.jpg"
    photo_path.write_bytes(b"fake-jpeg-bytes")

    stored_name = mod.archive_photo_as_document(12345, photo_path, reason="не распознано как еда")

    saved_file = tmp_path / "data" / "uploads" / "12345" / stored_name
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"fake-jpeg-bytes"

    kb_path = tmp_path / "data" / "kb" / "kb_12345.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(data["documents"]) == 1
    doc_entry = data["documents"][0]
    assert doc_entry["file"] == stored_name
    assert doc_entry["auto_archived"] is True
    assert doc_entry["user_confirmed"] is False
    assert doc_entry["reason"] == "не распознано как еда"


def test_archive_photo_as_document_saved_on_request_sets_title_category(tmp_path, monkeypatch):
    """Фаза 3 (issue #370): явная просьба сохранить — auto_archived=False,
    user_confirmed=True, title/category и saved_on_request записаны."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    photo_path = tmp_path / "policy.jpg"
    photo_path.write_bytes(b"fake-policy-bytes")

    stored_name = mod.archive_photo_as_document(
        777,
        photo_path,
        title="Полис ОМС",
        category="insurance",
        saved_on_request=True,
    )

    kb_path = tmp_path / "data" / "kb" / "kb_777.json"
    doc_entry = json.loads(kb_path.read_text(encoding="utf-8"))["documents"][0]
    assert doc_entry["file"] == stored_name
    assert doc_entry["title"] == "Полис ОМС"
    assert doc_entry["category"] == "insurance"
    assert doc_entry["auto_archived"] is False
    assert doc_entry["user_confirmed"] is True
    assert doc_entry["saved_on_request"] is True


def test_save_files_on_request_saves_single_file(tmp_path, monkeypatch):
    import handlers.doc_upload as mod
    from handlers import doc_dedup

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    doc_dedup.reset()

    photo_path = tmp_path / "insurance.jpg"
    photo_path.write_bytes(b"insurance-bytes")

    titles = mod.save_files_on_request(555, [photo_path], "сохрани полис ОМС")

    assert titles == ["полис ОМС"]
    kb_path = tmp_path / "data" / "kb" / "kb_555.json"
    doc_entry = json.loads(kb_path.read_text(encoding="utf-8"))["documents"][0]
    assert doc_entry["title"] == "полис ОМС"
    assert doc_entry["category"] == "insurance"
    assert doc_entry["saved_on_request"] is True
    doc_dedup.reset()


def test_save_files_on_request_dedup_skips_recent_duplicate(tmp_path, monkeypatch):
    """Тот же контент уже помечен doc_dedup как STATUS_SAVED — не сохраняем
    повторно (issue #370, фаза 3: «не сохранять тот же файл дважды подряд»)."""
    import handlers.doc_upload as mod
    from handlers import doc_dedup

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    doc_dedup.reset()

    photo_path = tmp_path / "dup.jpg"
    content = b"duplicate-bytes"
    photo_path.write_bytes(content)
    doc_dedup.mark_saved(999, content)

    titles = mod.save_files_on_request(999, [photo_path], "сохрани на всякий случай")

    assert titles == []
    kb_path = tmp_path / "data" / "kb" / "kb_999.json"
    assert not kb_path.exists()
    doc_dedup.reset()


def test_save_files_on_request_album_shares_title(tmp_path, monkeypatch):
    """Альбом с одной подписью — все файлы сохраняются под одним title."""
    import handlers.doc_upload as mod
    from handlers import doc_dedup

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    doc_dedup.reset()

    p1 = tmp_path / "a.jpg"
    p2 = tmp_path / "b.jpg"
    p1.write_bytes(b"page-1")
    p2.write_bytes(b"page-2")

    titles = mod.save_files_on_request(111, [p1, p2], "сохрани справку от врача")

    assert titles == ["справку от врача", "справку от врача"]
    kb_path = tmp_path / "data" / "kb" / "kb_111.json"
    docs = json.loads(kb_path.read_text(encoding="utf-8"))["documents"]
    assert len(docs) == 2
    assert all(d["title"] == "справку от врача" for d in docs)
    doc_dedup.reset()


def test_preview_shows_allergies_new_vs_existing():
    from handlers.doc_upload import _preview_text

    extracted = {"values": {}, "allergies": ["Пыльца", "Кошки"], "conditions": []}
    existing = {"allergies": ["Пыльца"], "chronic_conditions": []}
    text = _preview_text(extracted, existing)
    assert "Кошки" in text
    assert "Пыльца" in text
    assert text.count("🆕") >= 1


def test_preview_conditions_only_is_not_archive():
    from handlers.doc_upload import _preview_text

    extracted = {"values": {}, "allergies": [], "conditions": ["Астма (J45.0)"]}
    text = _preview_text(extracted, {})
    assert "Астма (J45.0)" in text
    assert "не нашёл" not in text.lower()


def test_preview_truly_empty_is_archive():
    from handlers.doc_upload import _preview_text

    text = _preview_text({"values": {}, "allergies": [], "conditions": []}, {})
    assert "не нашёл" in text.lower() or "архив" in text.lower()


@pytest.mark.asyncio
async def test_cmd_doc_sets_fsm_state():
    """Команда /doc переводит в состояние DocUpload.waiting."""
    from handlers.doc_upload import cmd_doc

    msg = _make_message(text="/doc", from_id=12345)
    state = AsyncMock()
    state.set_state = AsyncMock()

    await cmd_doc(msg, state)

    state.set_state.assert_called_once()
    msg.answer.assert_called_once()


def test_read_existing_profile_reads_onboarding(test_db, monkeypatch):
    import handlers.doc_upload as mod
    from database.models import User

    test_db.add(
        User(
            telegram_id=555,
            first_name="Т",
            is_active=True,
            cohort="external",
            pack_name="generic",
            onboarding_data={"allergies": ["Пыльца"]},
        )
    )
    test_db.commit()
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    prof = mod._read_existing_profile(555)
    assert prof["allergies"] == ["Пыльца"]
    assert prof["chronic_conditions"] == []


@pytest.mark.asyncio
async def test_doc_received_album_is_queued_not_rejected(tmp_path, test_db, monkeypatch):
    """issue #499: альбом из нескольких файлов больше не отбивается — оба
    файла ставятся в очередь, первый обрабатывается сразу с пометкой прогресса."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    def _doc_message(file_name, mime_type, content, from_id=999):
        doc = MagicMock()
        doc.file_name = file_name
        doc.mime_type = mime_type
        doc.file_size = len(content)
        doc.file_id = f"file-{file_name}"

        processing = AsyncMock()
        processing.edit_text = AsyncMock()

        msg = MagicMock()
        msg.document = doc
        msg.photo = None
        msg.from_user.id = from_id
        msg.caption = None
        msg.answer = AsyncMock(return_value=processing)
        msg.bot = AsyncMock()
        msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/on/tg"))

        async def fake_download(file_path, buf):
            buf.write(content)

        msg.bot.download_file = AsyncMock(side_effect=fake_download)
        return msg, processing

    msg1, processing1 = _doc_message("a.pdf", "application/pdf", b"%PDF-a")
    msg2, _ = _doc_message("b.jpg", "image/jpeg", b"\xff\xd8-b")
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    extracted = {"values": {"Hb": 150}}
    with (
        patch("handlers.photo._extract_pdf_text", return_value="Общий анализ крови\nHb 150 г/л"),
        patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)),
    ):
        await mod.doc_received(msg1, state, album=[msg1, msg2])

    # Первый файл разобран сразу, очередь получила второй.
    queue_call = [c for c in state.update_data.call_args_list if "queue" in c.kwargs]
    assert queue_call, "queue должен был попасть в FSM"
    assert len(queue_call[0].kwargs["queue"]) == 1

    processing1.edit_text.assert_called_once()
    intro_or_preview = processing1.edit_text.call_args[0][0]
    assert "Hb" in intro_or_preview


@pytest.mark.asyncio
async def test_doc_confirm_save_merges_into_onboarding(test_db, tmp_path, monkeypatch):
    import handlers.doc_upload as mod
    from database.models import User

    test_db.add(
        User(
            telegram_id=777,
            first_name="Т",
            is_active=True,
            cohort="external",
            pack_name="generic",
            onboarding_data={},
        )
    )
    test_db.commit()
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    uploads = tmp_path / "data" / "uploads" / "777"
    uploads.mkdir(parents=True)
    pending = uploads / ".pending_2026-07-14_abcd1234.pdf"
    pending.write_bytes(b"x")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = 777
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending),
                "stored_name": "2026-07-14_abcd1234.pdf",
                "extracted": {"values": {}, "allergies": ["Пыльца"], "conditions": ["Астма"]},
            }
        }
    )
    state.update_data = AsyncMock()

    await mod.doc_confirm(callback, state)

    u = test_db.query(User).filter_by(telegram_id=777).one()
    assert u.onboarding_data["allergies"] == ["Пыльца"]
    assert u.onboarding_data["chronic_conditions"] == ["Астма"]
    final_text = callback.message.edit_text.call_args[0][0]
    assert "аллергии" in final_text.lower() and "1" in final_text


# ── run_doc_pipeline (issue #439) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_doc_pipeline_sets_fsm_and_shows_preview(tmp_path, test_db, monkeypatch):
    """Ядро doc-пайплайна: ставит DocUpload.waiting, кладёт pending в state,
    показывает превью найденных значений с клавиатурой подтверждения."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(from_id=555)
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()

    extracted = {"date": "2026-08-01", "laboratory": "KDL", "values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    state.set_state.assert_called_once_with(mod.DocUpload.waiting)
    state.update_data.assert_called_once()
    pending = state.update_data.call_args.kwargs["pending"]
    assert pending["extracted"] == extracted
    assert "caption" not in pending

    processing.edit_text.assert_called_once()
    preview_text = processing.edit_text.call_args[0][0]
    assert "Hb" in preview_text
    keyboard = processing.edit_text.call_args.kwargs["reply_markup"]
    callback_data = {btn.callback_data for row in keyboard.inline_keyboard for btn in row}
    assert callback_data == {"docup_save", "docup_cancel"}


@pytest.mark.asyncio
async def test_run_doc_pipeline_stores_caption_and_notes_it_in_preview(tmp_path, test_db, monkeypatch):
    """Caption с вопросом — сохраняется в pending и упоминается в превью
    (issue #439 п.4: ответ на вопрос приходит после сохранения)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(caption="это нормально?", from_id=556)
    state = AsyncMock()

    extracted = {"values": {"ALT": 24}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    pending = state.update_data.call_args.kwargs["pending"]
    assert pending["caption"] == "это нормально?"

    preview_text = processing.edit_text.call_args[0][0]
    assert "Отвечу" in preview_text


@pytest.mark.asyncio
async def test_run_doc_pipeline_pdf_extracts_from_text(tmp_path, test_db, monkeypatch):
    """PDF-ветка: если удалось вытащить текст — extract_medical_data вызывается
    на тексте, а не картинкой (без рендера страниц в PNG)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(from_id=557)
    state = AsyncMock()

    extract_mock = AsyncMock(return_value={"values": {"Hb": 140}})
    with (
        patch("handlers.photo._extract_pdf_text", return_value="Общий анализ крови\nHb 140 г/л"),
        patch("core.health.doc_extractor.extract_medical_data", extract_mock),
    ):
        await mod.run_doc_pipeline(message, state, content=b"%PDF-fake", ext=".pdf", is_pdf=True)

    extract_mock.assert_called_once()
    call_args = extract_mock.call_args.args
    assert call_args[1] == "text/plain"


@pytest.mark.asyncio
async def test_doc_received_still_shows_preview_after_refactor(tmp_path, test_db, monkeypatch):
    """/doc через doc_received (тонкая обёртка над run_doc_pipeline) ведёт себя
    как раньше: скачивает файл, показывает превью с клавиатурой."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    doc = MagicMock()
    doc.file_size = 1000
    doc.mime_type = "image/jpeg"
    doc.file_name = "scan.jpg"
    doc.file_id = "file123"

    msg = _make_message(document=doc, from_id=558)
    processing = AsyncMock()
    processing.edit_text = AsyncMock()
    msg.answer = AsyncMock(return_value=processing)
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/to/file"))

    async def fake_download(file_path, buf):
        buf.write(b"fake-jpeg-bytes")

    msg.bot.download_file = AsyncMock(side_effect=fake_download)

    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    extracted = {"values": {"Hb": 130}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.doc_received(msg, state, album=None)

    state.set_state.assert_called_once_with(mod.DocUpload.waiting)
    pending = state.update_data.call_args.kwargs["pending"]
    assert pending["extracted"] == extracted
    processing.edit_text.assert_called_once()
    assert "Hb" in processing.edit_text.call_args[0][0]


# ── issue #441 п.2: HTML-экранирование в превью ──────────────────────────────


def test_preview_text_escapes_html_special_chars():
    """Значение «<0.5» (типично для показателей ниже порога чувствительности)
    не должно попадать в HTML-превью необработанным — ломает Telegram-парсинг."""
    from handlers.doc_upload import _preview_text

    extracted = {"values": {"Ferritin": "<0.5"}}
    text = _preview_text(extracted)
    assert "<0.5" not in text
    assert "&lt;0.5" in text


@pytest.mark.asyncio
async def test_run_doc_pipeline_escapes_special_chars_in_preview(tmp_path, test_db, monkeypatch):
    """Сквозной прогон: значение «<0.5» из экстрактора доходит до превью
    экранированным, edit_text не падает (issue #441 п.2)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(from_id=559)
    state = AsyncMock()

    extracted = {"values": {"Ferritin": "<0.5"}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    processing.edit_text.assert_called_once()
    preview_text = processing.edit_text.call_args[0][0]
    assert "&lt;0.5" in preview_text


@pytest.mark.asyncio
async def test_run_doc_pipeline_retries_without_html_on_bad_request(tmp_path, test_db, monkeypatch):
    """Если Telegram всё равно не принял HTML-превью (TelegramBadRequest) —
    ретраим один раз без parse_mode вместо падения (issue #441 п.2)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(from_id=560)
    state = AsyncMock()

    bad_request = TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities")
    processing.edit_text = AsyncMock(side_effect=[bad_request, None])

    extracted = {"values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    assert processing.edit_text.call_count == 2
    second_call_kwargs = processing.edit_text.call_args_list[1].kwargs
    assert second_call_kwargs.get("parse_mode") is None


@pytest.mark.asyncio
async def test_run_doc_pipeline_archives_instead_of_deleting_when_preview_fails(tmp_path, test_db, monkeypatch):
    """Issue #516: если превью так и не удалось показать (ни с HTML, ни без,
    ни после ретраев на 429) — раньше это стирало FSM (`state.clear()`) и
    удаляло `.pending_*` файл (`unlink`), нарушая гарантию issue #370.
    Теперь документ архивируется под постоянным именем с KB-записью
    `auto_archived`, и FSM всё равно закрывается (issue #441 п.1 остаётся в
    силе — не зависаем в DocUpload.waiting без клавиатуры)."""
    import json

    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    message, processing = _make_message_with_processing(from_id=561)
    message.answer = AsyncMock(return_value=processing)
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={})  # заполнится через update_data(pending=...) внутри пайплайна
    state.update_data = AsyncMock(side_effect=lambda **kwargs: state.get_data.configure_mock(return_value=kwargs))
    processing.edit_text = AsyncMock(side_effect=RuntimeError("network is down"))

    extracted = {"values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        with pytest.raises(RuntimeError):
            await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    state.clear.assert_called_once()
    uploads = tmp_path / "data" / "uploads" / "561"
    assert list(uploads.glob(".pending_*")) == [], "не должно остаться зависшего .pending_*"

    archived_files = [f for f in uploads.iterdir() if not f.name.startswith(".")]
    assert len(archived_files) == 1, "документ должен быть перенесён в архив под постоянным именем, не удалён"

    kb_path = tmp_path / "data" / "kb" / "kb_561.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(data["documents"]) == 1
    entry = data["documents"][0]
    assert entry["auto_archived"] is True
    assert entry["user_confirmed"] is False

    # Пользователь получил спокойное сообщение о том, что документ сохранён.
    notify_calls = [c for c in message.answer.call_args_list if c.args and "архив" in c.args[0].lower()]
    assert notify_calls, "пользователь должен быть уведомлён, что документ сохранён в архив"


# ── issue #441 п.1/п.7а: авто-детект документы не оставляют FSM зависшим ────


@pytest.mark.asyncio
async def test_doc_confirm_save_clears_state_for_auto_detected_doc(tmp_path, test_db, monkeypatch):
    """Документ, попавший в пайплайн авто-детектом (не /doc) — после сохранения
    закрывает FSM целиком (state.clear()), а не остаётся в DocUpload.waiting.
    Иначе следующее фото еды или текст юзера попадали бы в doc-обработчики."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    uploads = tmp_path / "data" / "uploads" / "780"
    uploads.mkdir(parents=True)
    pending = uploads / ".pending_2026-07-14_abcd1234.pdf"
    pending.write_bytes(b"x")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = 780
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending),
                "stored_name": "2026-07-14_abcd1234.pdf",
                "extracted": {"values": {"Hb": 140}},
                "auto": True,
            }
        }
    )
    state.update_data = AsyncMock()

    await mod.doc_confirm(callback, state)

    state.clear.assert_called_once()
    final_text = callback.message.edit_text.call_args[0][0]
    assert "Пришли другой документ" not in final_text


@pytest.mark.asyncio
async def test_doc_confirm_cancel_auto_archives_instead_of_deleting(tmp_path, monkeypatch):
    """Отмена авто-детект документа НЕ удаляет файл молча — архивирует его как
    auto_archived/user_confirmed=False (гарантия issue #370: файл никогда просто
    не исчезает, распространяется и на отмену авто-разбора)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    uploads = tmp_path / "data" / "uploads" / "781"
    uploads.mkdir(parents=True)
    pending = uploads / ".pending_2026-07-14_deadbeef.jpg"
    pending.write_bytes(b"jpeg-bytes")

    callback = MagicMock()
    callback.data = "docup_cancel"
    callback.from_user.id = 781
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending),
                "stored_name": "2026-07-14_deadbeef.jpg",
                "extracted": {},
                "auto": True,
            }
        }
    )

    await mod.doc_confirm(callback, state)

    state.clear.assert_called_once()
    final_path = uploads / "2026-07-14_deadbeef.jpg"
    assert final_path.exists(), "файл должен остаться в архиве, не удаляться"
    assert not pending.exists()

    kb_path = tmp_path / "data" / "kb" / "kb_781.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    doc_entry = data["documents"][0]
    assert doc_entry["auto_archived"] is True
    assert doc_entry["user_confirmed"] is False
    assert doc_entry["reason"] == "пользователь отменил разбор"

    final_text = callback.message.edit_text.call_args[0][0]
    assert "архив" in final_text.lower()


@pytest.mark.asyncio
async def test_doc_confirm_cancel_non_auto_still_deletes_file(tmp_path, monkeypatch):
    """/doc — пользователь сам явно вошёл в режим загрузки; отмена по-прежнему
    значит «выбросить», как и до issue #441 (регресс-guard)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    uploads = tmp_path / "data" / "uploads" / "782"
    uploads.mkdir(parents=True)
    pending = uploads / ".pending_2026-07-14_cafebabe.jpg"
    pending.write_bytes(b"jpeg-bytes")

    callback = MagicMock()
    callback.data = "docup_cancel"
    callback.from_user.id = 782
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending),
                "stored_name": "2026-07-14_cafebabe.jpg",
                "extracted": {},
            }
        }
    )
    state.update_data = AsyncMock()

    await mod.doc_confirm(callback, state)

    assert not pending.exists()
    kb_path = tmp_path / "data" / "kb" / "kb_782.json"
    assert not kb_path.exists()
    final_text = callback.message.edit_text.call_args[0][0]
    assert "не сохранил" in final_text.lower()
    state.clear.assert_not_called()


# ── issue #441 п.7б: чистка зависших .pending_* ──────────────────────────────


@pytest.mark.asyncio
async def test_run_doc_pipeline_archives_stale_pending_files_not_deletes(tmp_path, test_db, monkeypatch):
    """Issue #516: .pending_*/.queued_* файлы старше 24ч (из прошлых упавших
    запусков, или осиротевшие после рестарта бота посреди разбора пачки —
    FSM в MemoryStorage теряется целиком) раньше УДАЛЯЛИСЬ сторожем
    (`f.unlink`), нарушая гарантию issue #370. Теперь они архивируются под
    постоянным именем с KB-записью `auto_archived`, причина «не дождался
    разбора». Свежие файлы (моложе порога) не трогаем."""
    import json
    import os

    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 562
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)
    stale = uploads / ".pending_2026-01-01_stale0001.jpg"
    stale.write_bytes(b"old")
    stale_queued = uploads / ".queued_2026-01-01_stale0002.jpg"
    stale_queued.write_bytes(b"old-queued")
    fresh = uploads / ".pending_2026-08-01_fresh001.jpg"
    fresh.write_bytes(b"new")

    old_time = time.time() - 25 * 3600
    os.utime(stale, (old_time, old_time))
    os.utime(stale_queued, (old_time, old_time))

    message, processing = _make_message_with_processing(from_id=user_id)
    state = AsyncMock()

    extracted = {"values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    assert not stale.exists(), "зависший .pending_* старше 24ч больше не должен лежать под старым именем"
    assert not stale_queued.exists(), "зависший .queued_* старше 24ч больше не должен лежать под старым именем"
    assert fresh.exists(), "свежий .pending_* не должен трогаться"

    assert (uploads / "2026-01-01_stale0001.jpg").exists(), (
        "архивный .pending_* должен остаться на диске под постоянным именем"
    )
    assert (uploads / "2026-01-01_stale0002.jpg").exists(), (
        "архивный .queued_* должен остаться на диске под постоянным именем"
    )

    kb_path = tmp_path / "data" / "kb" / f"kb_{user_id}.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    archived_entries = {d["file"]: d for d in data["documents"]}
    assert "2026-01-01_stale0001.jpg" in archived_entries
    assert "2026-01-01_stale0002.jpg" in archived_entries
    for entry in archived_entries.values():
        assert entry["auto_archived"] is True
        assert entry["user_confirmed"] is False
        assert entry["reason"] == "не дождался разбора"


# ── issue #441 п.8: is_medical_document ──────────────────────────────────────


def test_is_medical_document_true_for_lab_report():
    from handlers.doc_upload import is_medical_document

    assert is_medical_document({"type": "medical", "data": {"subtype": "lab_report"}}) is True


def test_is_medical_document_false_for_medication_package():
    from handlers.doc_upload import is_medical_document

    assert is_medical_document({"type": "medical", "data": {"subtype": "medication_package"}}) is False


def test_is_medical_document_true_when_subtype_missing():
    from handlers.doc_upload import is_medical_document

    assert is_medical_document({"type": "medical", "data": {}}) is True


def test_is_medical_document_false_for_other_type_and_bad_input():
    from handlers.doc_upload import is_medical_document

    assert is_medical_document({"type": "other", "data": {}}) is False
    assert is_medical_document(None) is False
    assert is_medical_document("not a dict") is False


# ── issue #499: очередь документов (альбом/ZIP) ──────────────────────────────


@pytest.mark.asyncio
async def test_doc_confirm_save_advances_to_next_queued_item(tmp_path, test_db, monkeypatch):
    """После сохранения текущего документа, если в очереди есть следующий —
    сразу запускается его разбор с пометкой «Документ 2 из 2»."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    uploads = tmp_path / "data" / "uploads" / "900"
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-22_aaaa1111.pdf"
    pending_path.write_bytes(b"%PDF-first")
    queued_path = uploads / ".queued_2026-09-22_bbbb2222.jpg"
    queued_path.write_bytes(b"\xff\xd8-second")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = 900
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock(return_value=AsyncMock(edit_text=AsyncMock()))
    callback.answer = AsyncMock()

    fsm_data = {
        "pending": {
            "tmp_path": str(pending_path),
            "stored_name": "2026-09-22_aaaa1111.pdf",
            "extracted": {"values": {"Hb": 140}},
        },
        "queue": [
            {"tmp_path": str(queued_path), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"},
        ],
        "queue_total": 2,
    }
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=fsm_data)
    state.update_data = AsyncMock()

    extracted2 = {"values": {"ALT": 24}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted2)):
        await mod.doc_confirm(callback, state)

    # Первый документ сохранён.
    kb_path = tmp_path / "data" / "kb" / "kb_900.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert data["documents"][0]["user_confirmed"] is True

    # Очередь обновлена — второй элемент выгружен из неё.
    queue_updates = [c for c in state.update_data.call_args_list if "queue" in c.kwargs]
    assert queue_updates
    assert queue_updates[-1].kwargs["queue"] == []

    # Второй элемент уже читается — новое сообщение с прогрессом отправлено.
    callback.message.answer.assert_called_once()
    intro_text = callback.message.answer.call_args[0][0]
    assert "2" in intro_text and "из" in intro_text

    # .queued_* файл больше не существует (перечитан и удалён), .pending_*
    # для второго элемента создан заново процессом run_doc_pipeline.
    assert not queued_path.exists()
    assert list(uploads.glob(".pending_*"))


@pytest.mark.asyncio
async def test_doc_confirm_cancel_advances_to_next_queued_item(tmp_path, test_db, monkeypatch):
    """Отмена текущего документа тоже продолжает очередь, а не просто
    закрывает /doc — иначе следующий файл пришлось бы присылать заново."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    uploads = tmp_path / "data" / "uploads" / "901"
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-22_cccc3333.pdf"
    pending_path.write_bytes(b"%PDF-first")
    queued_path = uploads / ".queued_2026-09-22_dddd4444.jpg"
    queued_path.write_bytes(b"\xff\xd8-second")

    callback = MagicMock()
    callback.data = "docup_cancel"
    callback.from_user.id = 901
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock(return_value=AsyncMock(edit_text=AsyncMock()))
    callback.answer = AsyncMock()

    fsm_data = {
        "pending": {"tmp_path": str(pending_path), "stored_name": "2026-09-22_cccc3333.pdf", "extracted": {}},
        "queue": [{"tmp_path": str(queued_path), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"}],
        "queue_total": 2,
    }
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=fsm_data)
    state.update_data = AsyncMock()

    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value={})):
        await mod.doc_confirm(callback, state)

    assert not pending_path.exists()  # первый документ выброшен, как при обычной отмене
    callback.message.answer.assert_called_once()  # второй документ уже читается


@pytest.mark.asyncio
async def test_cmd_cancel_archives_pending_and_queue(tmp_path, monkeypatch):
    """issue #499: /cancel посреди батча не роняет файлы молча — и текущий,
    и весь хвост очереди архивируются (гарантия issue #370)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    uploads = tmp_path / "data" / "uploads" / "902"
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-22_eeee5555.pdf"
    pending_path.write_bytes(b"%PDF-current")
    queued_path = uploads / ".queued_2026-09-22_ffff6666.jpg"
    queued_path.write_bytes(b"\xff\xd8-queued")

    msg = _make_message(text="/cancel", from_id=902)
    fsm_data = {
        "pending": {"tmp_path": str(pending_path), "stored_name": "2026-09-22_eeee5555.pdf", "extracted": {}},
        "queue": [{"tmp_path": str(queued_path), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"}],
        "queue_total": 2,
    }
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=fsm_data)
    state.clear = AsyncMock()

    await mod.cmd_cancel(msg, state)

    state.clear.assert_called_once()
    assert not pending_path.exists()
    assert not queued_path.exists()
    assert (uploads / "2026-09-22_eeee5555.pdf").exists()
    assert (uploads / "2026-09-22_ffff6666.jpg").exists()

    kb_path = tmp_path / "data" / "kb" / "kb_902.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(data["documents"]) == 2
    assert all(d["auto_archived"] is True and d["user_confirmed"] is False for d in data["documents"])

    reply_text = msg.answer.call_args[0][0]
    assert "2" in reply_text


# ── issue #516: сбой показа превью / рестарт не роняют пачку документов ────


class _StatefulFSM:
    """Простая in-memory замена FSMContext для тестов, где важно, чтобы
    update_data/get_data/clear реально согласованно меняли одно и то же
    состояние между вызовами (в отличие от AsyncMock с фиксированным
    return_value) — нужно для сценариев, где run_doc_pipeline сам себе
    читает/пишет `pending`/`queue` в несколько шагов."""

    def __init__(self, data=None):
        self._data = dict(data or {})
        self.cleared = False

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, _state):
        pass

    async def clear(self):
        self._data = {}
        self.cleared = True


@pytest.mark.asyncio
async def test_preview_failure_mid_batch_archives_entire_batch_none_deleted(tmp_path, test_db, monkeypatch):
    """DoD issue #516: сбой edit_text на втором документе пачки из трёх —
    все три документа оказываются в архиве (KB-записи + файлы под
    постоянными именами), ни один не удалён."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 950
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)

    # Пачка из трёх: документ 1 — текущий pending (будет сохранён обычным
    # путём), документ 2 и 3 — ещё в очереди (.queued_*, не показывались).
    # После сохранения документа 1 пайплайн сам поднимет документ 2 из
    # очереди и попытается показать его превью — вот тут и сработает сбой.
    pending1 = uploads / ".pending_2026-09-22_aaaa0001.pdf"
    pending1.write_bytes(b"%PDF-one")
    queued2 = uploads / ".queued_2026-09-22_bbbb0002.jpg"
    queued2.write_bytes(b"\xff\xd8-two")
    queued3 = uploads / ".queued_2026-09-22_cccc0003.jpg"
    queued3.write_bytes(b"\xff\xd8-three")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    processing2 = AsyncMock()
    processing2.edit_text = AsyncMock(side_effect=RuntimeError("edit failed"))
    callback.message.answer = AsyncMock(return_value=processing2)

    callback.answer = AsyncMock()

    state = _StatefulFSM(
        {
            "pending": {
                "tmp_path": str(pending1),
                "stored_name": "2026-09-22_aaaa0001.pdf",
                "extracted": {"values": {"Hb": 140}},
            },
            "queue": [
                {"tmp_path": str(queued2), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"},
                {"tmp_path": str(queued3), "ext": ".jpg", "is_pdf": False, "label": "c.jpg"},
            ],
            "queue_total": 3,
        }
    )

    extracted2 = {"values": {"ALT": 24}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted2)):
        with pytest.raises(RuntimeError):
            await mod.doc_confirm(callback, state)

    kb_path = tmp_path / "data" / "kb" / f"kb_{user_id}.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    # Документ 1 — обычное сохранение (user_confirmed=True), документ 2 и 3 —
    # archived после сбоя показа превью документа 2 (документ 3 — хвост
    # очереди, никогда не показывался).
    assert len(data["documents"]) == 3
    by_file = {d["file"]: d for d in data["documents"]}
    assert by_file["2026-09-22_aaaa0001.pdf"]["user_confirmed"] is True
    # Имя документа 2 генерируется динамически из его контента внутри
    # run_doc_pipeline — найдём его по auto_archived (документы 2 и 3), а не
    # по конкретному имени файла.
    archived_docs = [d for d in data["documents"] if d.get("auto_archived") is True]
    assert len(archived_docs) == 2
    assert all(d["user_confirmed"] is False for d in archived_docs)

    # Ни один файл не удалён — все лежат на диске под постоянными именами
    # (без ведущей точки/префикса .pending_/.queued_).
    remaining = [f.name for f in uploads.iterdir()]
    assert not any(name.startswith(".pending_") or name.startswith(".queued_") for name in remaining)
    assert len(remaining) == 3, f"ожидали 3 архивных файла на диске, получили: {remaining}"


@pytest.mark.asyncio
async def test_telegram_retry_after_is_not_fatal_retries_and_succeeds(tmp_path, test_db, monkeypatch):
    """DoD issue #516: TelegramRetryAfter (429) приводит к ожиданию и
    повтору, а не к очистке/архивации — превью в итоге показывается
    успешно."""
    import handlers.doc_upload as mod
    from aiogram.exceptions import TelegramRetryAfter

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)

    message, processing = _make_message_with_processing(from_id=563)
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()

    flood_error = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=2)
    processing.edit_text = AsyncMock(side_effect=[flood_error, None])

    extracted = {"values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    assert processing.edit_text.call_count == 2
    assert sleep_calls == [2]
    state.clear.assert_not_called()
    uploads = tmp_path / "data" / "uploads" / "563"
    # Файл остался как .pending_* (ждёт подтверждения) — не архивирован и не удалён.
    assert list(uploads.glob(".pending_*"))


@pytest.mark.asyncio
async def test_telegram_retry_after_gives_up_after_max_attempts_and_archives(tmp_path, test_db, monkeypatch):
    """429 продолжает сыпаться дольше разумного числа попыток — не висим
    вечно, документ архивируется как при любом другом неустранимом сбое
    показа превью."""
    import handlers.doc_upload as mod
    from aiogram.exceptions import TelegramRetryAfter

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)

    message, processing = _make_message_with_processing(from_id=564)
    message.answer = AsyncMock(return_value=processing)
    state = _StatefulFSM()

    flood_error = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=1)
    processing.edit_text = AsyncMock(side_effect=flood_error)

    extracted = {"values": {"Hb": 150}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        with pytest.raises(TelegramRetryAfter):
            await mod.run_doc_pipeline(message, state, content=b"fake-jpeg", ext=".jpg", is_pdf=False)

    assert state.cleared
    uploads = tmp_path / "data" / "uploads" / "564"
    assert list(uploads.glob(".pending_*")) == []
    archived = [f for f in uploads.iterdir() if not f.name.startswith(".")]
    assert len(archived) == 1


@pytest.mark.asyncio
async def test_cancelled_document_can_be_resent_and_reparsed(tmp_path, test_db, monkeypatch):
    """DoD issue #516: файл, отменённый кнопкой «Отмена», при повторной
    отправке НЕ отклоняется дедупом как «уже разобранный» — разбирается
    заново (регресс сценария, обнаруженного на дев-стенде: ТТГ отменили,
    прислали снова, бот ответил «точный повтор»)."""
    import handlers.doc_upload as mod
    from handlers import doc_dedup
    from handlers.doc_queue import gather_source_files

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    doc_dedup.reset()
    user_id = 971
    content = b"%PDF-tsh-report"

    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-22_tttt0001.pdf"
    pending_path.write_bytes(content)

    # Симулируем, что gather_source_files уже пометил файл как "в обработке"
    # (как это происходит на реальном пути через doc_received).
    doc_dedup.mark_in_progress(user_id, content)

    callback = MagicMock()
    callback.data = "docup_cancel"
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending_path),
                "stored_name": "2026-09-22_tttt0001.pdf",
                "extracted": {},
            }
        }
    )
    state.update_data = AsyncMock()

    await mod.doc_confirm(callback, state)

    # Файл отменён (не сохранён) — но повторная отправка того же контента
    # больше не считается дублем.
    msg = _make_doc_message_for_dedup(content, from_id=user_id)
    result = await gather_source_files(user_id, [msg])
    assert len(result.items) == 1
    assert not result.skip_counts

    doc_dedup.reset()


@pytest.mark.asyncio
async def test_saved_document_resent_within_ttl_is_rejected_with_honest_text(tmp_path, test_db, monkeypatch):
    """DoD issue #516: документ, успешно сохранённый через docup_save, при
    повторной отправке в течение TTL отклоняется как дубль — с честным
    текстом «уже сохранил», а не «уже разобранного»."""
    import handlers.doc_upload as mod
    from handlers import doc_dedup
    from handlers.doc_queue import format_skip_summary, gather_source_files

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    doc_dedup.reset()
    user_id = 972
    content = b"%PDF-hba1c-report"

    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-22_uuuu0001.pdf"
    pending_path.write_bytes(content)
    doc_dedup.mark_in_progress(user_id, content)

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "pending": {
                "tmp_path": str(pending_path),
                "stored_name": "2026-09-22_uuuu0001.pdf",
                "extracted": {"values": {"Hb": 140}},
            }
        }
    )
    state.update_data = AsyncMock()

    await mod.doc_confirm(callback, state)

    msg = _make_doc_message_for_dedup(content, from_id=user_id)
    result = await gather_source_files(user_id, [msg])
    assert result.items == []
    assert result.skip_counts["duplicate_saved"] == 1
    summary = format_skip_summary(result.skip_counts)
    assert "уже" in summary.lower()
    assert "разобранного" not in summary.lower()

    doc_dedup.reset()


def _make_doc_message_for_dedup(content: bytes, from_id: int):
    """Мини doc-сообщение, совместимое с `gather_source_files` (то же, что
    `_make_doc_message` в test_doc_queue.py — не импортируем напрямую, чтобы
    не тянуть межфайловую зависимость тестов)."""
    doc = MagicMock()
    doc.file_name = "report.pdf"
    doc.mime_type = "application/pdf"
    doc.file_size = len(content)
    doc.file_id = "file-report.pdf"

    msg = MagicMock()
    msg.document = doc
    msg.photo = None
    msg.from_user.id = from_id
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/on/tg"))

    async def fake_download(file_path, buf):
        buf.write(content)

    msg.bot.download_file = AsyncMock(side_effect=fake_download)
    return msg


# ── issue #516 доп. (независимый ревьюер): очередь не теряет файлы ──────────


def _make_doc_message_dyn(file_name: str, mime_type: str, content: bytes, from_id: int):
    """Doc-сообщение с уникальным content — для тестов очереди/дедупа, где
    нужно несколько разных «файлов» подряд от одного юзера."""
    doc = MagicMock()
    doc.file_name = file_name
    doc.mime_type = mime_type
    doc.file_size = len(content)
    doc.file_id = f"file-{file_name}-{len(content)}"

    processing = AsyncMock()
    processing.edit_text = AsyncMock()

    msg = MagicMock()
    msg.document = doc
    msg.photo = None
    msg.from_user.id = from_id
    msg.caption = None
    msg.answer = AsyncMock(return_value=processing)
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/on/tg"))

    async def fake_download(file_path, buf):
        buf.write(content)

    msg.bot.download_file = AsyncMock(side_effect=fake_download)
    return msg, processing


@pytest.mark.asyncio
async def test_new_upload_during_active_queue_appends_not_replaces(tmp_path, test_db, monkeypatch):
    """Дефект А (независимый ревьюер): альбом из 3 файлов уже в очереди
    (документ 1 показан, ждёт подтверждения) — присланный ещё один файл
    ДОБАВЛЯЕТСЯ в хвост (4 элемента, прогресс «из 4»), а не заменяет очередь.
    Реальный сценарий: часть альбома пришла отдельным апдейтом из-за задержки
    MediaGroupMiddleware, либо пользователь дослал документ вручную."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 980
    msg1, processing1 = _make_doc_message_dyn("a.pdf", "application/pdf", b"%PDF-one", user_id)
    msg2, _ = _make_doc_message_dyn("b.jpg", "image/jpeg", b"\xff\xd8-two", user_id)
    msg3, _ = _make_doc_message_dyn("c.jpg", "image/jpeg", b"\xff\xd8-three", user_id)
    msg4, _ = _make_doc_message_dyn("d.jpg", "image/jpeg", b"\xff\xd8-four", user_id)

    state = _StatefulFSM()

    extracted = {"values": {"Hb": 150}}
    with (
        patch("handlers.photo._extract_pdf_text", return_value="Общий анализ крови\nHb 150 г/л"),
        patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)),
    ):
        # Альбом из трёх файлов — документ 1 сразу показывается, 2 и 3 в очереди.
        await mod.doc_received(msg1, state, album=[msg1, msg2, msg3])

    data_after_album = await state.get_data()
    assert data_after_album.get("pending") is not None
    assert len(data_after_album.get("queue") or []) == 2
    assert data_after_album.get("queue_total") == 3

    # Ещё один файл приходит, пока документ 1 всё ещё ждёт подтверждения.
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.doc_received(msg4, state, album=None)

    data_after_extra = await state.get_data()
    # Текущий pending (документ 1) не тронут.
    assert data_after_extra["pending"] == data_after_album["pending"]
    # Очередь выросла до 3 элементов (2 и 3 остались, добавился 4), всего 4.
    assert len(data_after_extra["queue"]) == 3
    assert data_after_extra["queue_total"] == 4

    # Пользователь уведомлён, что файл добавлен в очередь, а не начал новый показ.
    msg4.answer.assert_called_once()
    assert "очеред" in msg4.answer.call_args[0][0].lower()

    # Ничего не потеряно на диске: 1 pending + 3 queued = 4 файла.
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    all_files = list(uploads.glob(".pending_*")) + list(uploads.glob(".queued_*"))
    assert len(all_files) == 4


@pytest.mark.asyncio
async def test_concurrent_uploads_do_not_lose_any_item(tmp_path, test_db, monkeypatch):
    """Дефект А: два апдейта, обрабатываемые конкурентно (как это бывает под
    webhook — Dispatcher не изолирует события одного пользователя), не должны
    гонкой затирать очередь друг друга — оба файла должны остаться учтены
    (один — pending, другой — в очереди), суммарно ни один не потерян."""
    import asyncio as real_asyncio

    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 981
    msg1, _ = _make_doc_message_dyn("a.pdf", "application/pdf", b"%PDF-race-one", user_id)
    msg2, _ = _make_doc_message_dyn("b.jpg", "image/jpeg", b"\xff\xd8-race-two", user_id)

    state = _StatefulFSM()

    extracted = {"values": {"Hb": 150}}
    with (
        patch("handlers.photo._extract_pdf_text", return_value="Общий анализ крови\nHb 150 г/л"),
        patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)),
    ):
        await real_asyncio.gather(
            mod.doc_received(msg1, state, album=None),
            mod.doc_received(msg2, state, album=None),
        )

    data = await state.get_data()
    total_accounted = (1 if data.get("pending") else 0) + len(data.get("queue") or [])
    assert total_accounted == 2, f"ожидали учесть оба файла, получили: {data}"

    uploads = tmp_path / "data" / "uploads" / str(user_id)
    all_files = list(uploads.glob(".pending_*")) + list(uploads.glob(".queued_*"))
    assert len(all_files) == 2, f"ни один файл не должен потеряться на диске, нашли: {all_files}"


@pytest.mark.asyncio
async def test_stale_watchdog_does_not_touch_files_referenced_by_live_fsm(tmp_path, test_db, monkeypatch):
    """Дефект Б: пользователь мог просто вернуться к живой очереди на
    следующий день (MemoryStorage жив, рестарта не было) — файлы старше 24ч,
    на которые ссылается ТЕКУЩЕЕ FSM-состояние (pending и хвост очереди), не
    архивируются сторожем, иначе следующий docup_save/docup_cancel упадёт на
    пропавшем файле."""
    import os

    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 982
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)

    # Живой pending и живой хвост очереди — оба старше 24ч, но упомянуты в FSM.
    live_pending = uploads / ".pending_2026-01-01_live00p1.pdf"
    live_pending.write_bytes(b"%PDF-live-pending")
    live_queued = uploads / ".queued_2026-01-01_live00q1.jpg"
    live_queued.write_bytes(b"\xff\xd8-live-queued")
    old_time = time.time() - 25 * 3600
    os.utime(live_pending, (old_time, old_time))
    os.utime(live_queued, (old_time, old_time))

    state = _StatefulFSM(
        {
            "pending": {
                "tmp_path": str(live_pending),
                "stored_name": "2026-01-01_live00p1.pdf",
                "extracted": {},
            },
            "queue": [{"tmp_path": str(live_queued), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"}],
            "queue_total": 2,
        }
    )

    message, processing = _make_message_with_processing(from_id=user_id)
    extracted = {"values": {"Hb": 150}}
    # run_doc_pipeline вызовет _cleanup_stale_pending на КАЖДЫЙ запуск —
    # используем его напрямую для проверки, что живые файлы не тронуты.
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted)):
        await mod.run_doc_pipeline(message, state, content=b"unrelated-new-doc", ext=".jpg", is_pdf=False)

    assert live_pending.exists(), "живой pending не должен быть тронут сторожем"
    assert live_queued.exists(), "живой элемент очереди не должен быть тронут сторожем"

    kb_path = tmp_path / "data" / "kb" / f"kb_{user_id}.json"
    if kb_path.exists():
        data = json.loads(kb_path.read_text(encoding="utf-8"))
        archived_files = {d["file"] for d in data.get("documents", [])}
        assert "2026-01-01_live00p1.pdf" not in archived_files
        assert "2026-01-01_live00q1.jpg" not in archived_files


@pytest.mark.asyncio
async def test_missing_queue_file_is_skipped_with_message_and_callback_answers(tmp_path, test_db, monkeypatch):
    """Дефект Б: если файл элемента очереди пропал с диска — не роняем
    callback без ответа (`FileNotFoundError` в `_load_staged_item` раньше
    обрывал бы обработку) — пропускаем элемент с понятным сообщением и
    переходим к следующему живому элементу очереди."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 983
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)

    pending_path = uploads / ".pending_2026-09-23_missing1.pdf"
    pending_path.write_bytes(b"%PDF-current")

    # Второй элемент очереди — файл пропал с диска (не создаём его).
    missing_queued_path = uploads / ".queued_2026-09-23_gone0002.jpg"
    # Третий элемент — живой, должен быть показан вместо пропавшего.
    alive_queued_path = uploads / ".queued_2026-09-23_alive003.jpg"
    alive_queued_path.write_bytes(b"\xff\xd8-alive")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock(return_value=AsyncMock(edit_text=AsyncMock()))
    callback.answer = AsyncMock()

    state = _StatefulFSM(
        {
            "pending": {
                "tmp_path": str(pending_path),
                "stored_name": "2026-09-23_missing1.pdf",
                "extracted": {"values": {"Hb": 140}},
            },
            "queue": [
                {"tmp_path": str(missing_queued_path), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"},
                {"tmp_path": str(alive_queued_path), "ext": ".jpg", "is_pdf": False, "label": "c.jpg"},
            ],
            "queue_total": 3,
        }
    )

    extracted2 = {"values": {"ALT": 24}}
    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value=extracted2)):
        await mod.doc_confirm(callback, state)

    # Callback ответил — не завис молча.
    callback.answer.assert_called()
    callback.message.edit_text.assert_called()

    # Очередь продолжилась на живом элементе (третьем), а не оборвалась.
    data = await state.get_data()
    assert data.get("pending") is not None  # третий элемент теперь pending
    assert data.get("queue") == []

    # Пользователь получил понятное сообщение о пропущенном элементе — оно
    # приписано к тексту закрытия шага (edit_text), который видит сразу.
    edited_texts = [c.args[0] for c in callback.message.edit_text.call_args_list if c.args]
    assert any("пропустил" in t.lower() or "не наш" in t.lower() for t in edited_texts)


@pytest.mark.asyncio
async def test_intro_answer_failure_mid_batch_does_not_lose_document(tmp_path, test_db, monkeypatch):
    """Ревью координатора #516: при продолжении очереди load_staged_item
    читает .queued_ и СРАЗУ удаляет его с диска, а run_doc_pipeline первым
    делом шлёт message.answer(«Документ 2 из 3 — читаю…») — и только потом
    пишет .pending_. Если этот answer падает (429 после потолка ретраев,
    сеть), документ 2 исчезает отовсюду: его нет ни на диске, ни в очереди,
    ни в pending. Все три документа пачки должны оказаться в архиве."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    user_id = 951
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)
    pending1 = uploads / ".pending_2026-09-22_aaaa0011.pdf"
    pending1.write_bytes(b"%PDF-one")
    queued2 = uploads / ".queued_2026-09-22_bbbb0012.jpg"
    queued2.write_bytes(b"\xff\xd8-two")
    queued3 = uploads / ".queued_2026-09-22_cccc0013.jpg"
    queued3.write_bytes(b"\xff\xd8-three")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    # Сбой именно на «Документ 2 из 3 — читаю…», ДО записи .pending_ документа 2.
    callback.message.answer = AsyncMock(side_effect=RuntimeError("network down"))
    callback.answer = AsyncMock()

    state = _StatefulFSM(
        {
            "pending": {
                "tmp_path": str(pending1),
                "stored_name": "2026-09-22_aaaa0011.pdf",
                "extracted": {"values": {"Hb": 140}},
            },
            "queue": [
                {"tmp_path": str(queued2), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"},
                {"tmp_path": str(queued3), "ext": ".jpg", "is_pdf": False, "label": "c.jpg"},
            ],
            "queue_total": 3,
        }
    )

    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value={"values": {}})):
        with pytest.raises(RuntimeError):
            await mod.doc_confirm(callback, state)

    kb_path = tmp_path / "data" / "kb" / f"kb_{user_id}.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    files = {d["file"] for d in data["documents"]}
    assert len(data["documents"]) == 3, files
    # содержимое документа 2 физически сохранено под постоянным именем
    assert any((uploads / f).exists() and (uploads / f).read_bytes() == b"\xff\xd8-two" for f in files)


def test_cancel_with_claiming_marker_does_not_crash_and_archives_tail(tmp_path, monkeypatch):
    """Ревью координатора #516: doc_received на чистом старте ставит
    pending={"claiming": True} — маркер без tmp_path. Если run_doc_pipeline
    упал до записи настоящего pending, маркер застревает, и /cancel падал с
    KeyError на pending["tmp_path"] — пользователь не мог выйти из сессии."""
    import handlers.doc_upload as mod
    from handlers.doc_queue import archive_leftover_documents

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")

    user_id = 952
    uploads = tmp_path / "data" / "uploads" / str(user_id)
    uploads.mkdir(parents=True)
    queued = uploads / ".queued_2026-09-22_dddd0014.jpg"
    queued.write_bytes(b"\xff\xd8-tail")

    data = {
        "pending": {"claiming": True},
        "queue": [{"tmp_path": str(queued), "ext": ".jpg", "is_pdf": False, "label": "d.jpg"}],
    }
    archived = archive_leftover_documents(user_id, data)

    assert archived == 1
    assert not queued.exists()


def test_preview_says_unreadable_when_model_returned_nothing():
    """Честный текст про плохое качество скана — даже если модель сама
    вернула пустой список и отбрасывать было нечего."""
    from handlers.doc_upload import _preview_text

    text = _preview_text({"values": {}, "_unverified_labels": [], "_unreadable_text": True}, {})
    assert "читается плохо" in text


@pytest.mark.asyncio
async def test_doc_confirm_save_auto_detected_with_queue_advances_not_drops(tmp_path, test_db, monkeypatch):
    """Прецедент 24.09.2026: альбом из 16 фото анализов без /doc. Первое фото
    ушло в пайплайн авто-детектом (auto=True), остальные встали в очередь через
    doc_received. После «Сохранить» очередь раньше выбрасывалась (state.clear()
    для auto), и 10 файлов навсегда оставались `.queued_*` на диске. Теперь
    очередь продолжается, а auto-признак переходит на следующий элемент — чтобы
    после последнего документа FSM всё равно закрылся (#441 п.1)."""
    import handlers.doc_upload as mod

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_UPLOADS_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)

    uploads = tmp_path / "data" / "uploads" / "901"
    uploads.mkdir(parents=True)
    pending_path = uploads / ".pending_2026-09-24_aaaa1111.jpg"
    pending_path.write_bytes(b"\xff\xd8-first")
    queued_path = uploads / ".queued_2026-09-24_bbbb2222.jpg"
    queued_path.write_bytes(b"\xff\xd8-second")

    callback = MagicMock()
    callback.data = "docup_save"
    callback.from_user.id = 901
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock(return_value=AsyncMock(edit_text=AsyncMock()))
    callback.answer = AsyncMock()

    fsm_data = {
        "pending": {
            "tmp_path": str(pending_path),
            "stored_name": "2026-09-24_aaaa1111.jpg",
            "extracted": {"values": {"Hb": 119}},
            "auto": True,
        },
        "queue": [
            {"tmp_path": str(queued_path), "ext": ".jpg", "is_pdf": False, "label": "b.jpg"},
        ],
        "queue_total": 2,
    }
    state = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value=fsm_data)
    state.update_data = AsyncMock()

    with patch("core.health.doc_extractor.extract_medical_data", AsyncMock(return_value={"values": {"ALT": 24}})):
        await mod.doc_confirm(callback, state)

    state.clear.assert_not_called()
    assert not queued_path.exists()
    callback.message.answer.assert_called_once()
    pending_updates = [c.kwargs["pending"] for c in state.update_data.call_args_list if "pending" in c.kwargs]
    assert pending_updates and pending_updates[-1].get("auto") is True


def test_preview_shows_summary_escaped_and_counts_as_content():
    """#558: у мазка нет чисел, но есть резюме — это не «ничего не нашёл»."""
    import handlers.doc_upload as mod

    extracted = {
        "date": "2026-09-08",
        "doc_type": "ПЦР на ВПЧ",
        "summary": "ДНК ВПЧ ВКР — не обнаружено; порог <3 lg",
        "values": {},
    }
    assert mod._has_content(extracted) is True
    text = mod._preview_text(extracted)
    assert "ПЦР на ВПЧ" in text
    assert "не обнаружено; порог &lt;3 lg" in text
    assert "Не нашёл данных" not in text
