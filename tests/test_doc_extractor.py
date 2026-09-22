# tests/test_doc_extractor.py
import json
import pytest
from unittest.mock import AsyncMock, patch

from core.health import doc_extractor
from core.health.kb_schema import CANONICAL


# ── system prompt содержит канонические ключи (issue #445) ──────────────────


def test_system_prompt_contains_all_canonical_keys():
    """Промпт экстрактора должен перечислять все ключи CANONICAL — иначе модель

    придумывает свои варианты (neutrophils_band vs band_neutrophils) и они тихо
    теряются в to_canonical. Guard от рассинхрона при добавлении новых маркеров
    в реестр без обновления промпта.
    """
    missing = [key for key in CANONICAL if key not in doc_extractor._SYSTEM_PROMPT]
    assert missing == [], f"ключи не попали в системный промпт: {missing}"


def test_build_system_prompt_matches_module_constant():
    """`_build_system_prompt()` — источник `_SYSTEM_PROMPT`, оба должны совпадать."""
    assert doc_extractor._build_system_prompt() == doc_extractor._SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_extract_returns_dict_on_success():
    """Экстрактор возвращает dict с date/laboratory/values при валидном ответе Claude."""
    mock_response = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"date": "2026-04-13", "laboratory": "KDL", "values": {"Hb": 165, "ferritin": 112}}),
            }
        ]
    }
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data

        result = await extract_medical_data(b"fake-pdf-bytes", "application/pdf")
    assert result["date"] == "2026-04-13"
    assert result["values"]["Hb"] == 165


@pytest.mark.asyncio
async def test_extract_returns_empty_dict_when_no_values_found():
    """Экстрактор возвращает {} если Claude ничего не нашёл."""
    mock_response = {"content": [{"type": "text", "text": "{}"}]}
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data

        result = await extract_medical_data(b"fake-bytes", "image/jpeg")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_handles_malformed_json_gracefully():
    """Если Claude вернул не-JSON — возвращаем {}, не падаем."""
    mock_response = {"content": [{"type": "text", "text": "Я не нашёл ничего в документе."}]}
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data

        result = await extract_medical_data(b"fake-bytes", "image/jpeg")
    assert result == {}


def _fake_response(payload: dict) -> dict:
    return {"content": [{"text": json.dumps(payload, ensure_ascii=False)}]}


@pytest.mark.asyncio
async def test_extract_returns_allergies_and_conditions():
    payload = {
        "date": "2026-04-13",
        "laboratory": None,
        "values": {},
        "allergies": ["пыльца", "кошки"],
        "conditions": ["Бронхиальная астма (J45.0)"],
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/png")
    assert out["allergies"] == ["пыльца", "кошки"]
    assert out["conditions"] == ["Бронхиальная астма (J45.0)"]


@pytest.mark.asyncio
async def test_extract_missing_qualitative_defaults_to_empty_lists():
    payload = {"date": None, "laboratory": None, "values": {"Hb": 155}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/png")
    assert out["allergies"] == []
    assert out["conditions"] == []
    assert out["values"] == {"Hb": 155}


@pytest.mark.asyncio
async def test_extract_coerces_nonlist_qualitative_to_empty():
    payload = {"values": {}, "allergies": "пыльца", "conditions": None}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/png")
    assert out["allergies"] == []
    assert out["conditions"] == []


@pytest.mark.asyncio
async def test_text_plain_builds_text_block_not_image():
    """text/plain (текстовый слой PDF) уходит как text-блок, а не image с битым media_type."""
    doc_text = "Заключение: аллергия на амоксициллин. Гастрит (K29.5)."
    mock = AsyncMock(return_value=_fake_response({"values": {}}))
    with patch.object(doc_extractor, "_call_anthropic", new=mock):
        await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    messages = mock.call_args.args[0]
    content = messages[0]["content"]
    # Есть text-блок с самим текстом документа
    assert any(b.get("type") == "text" and doc_text in b.get("text", "") for b in content)
    # И НЕТ image-блока с невалидным media_type text/plain
    assert not any(b.get("type") == "image" for b in content)


@pytest.mark.asyncio
async def test_text_plain_extracts_values():
    """Путь text/plain доходит до парсинга ответа и возвращает извлечённые данные,

    если название показателя реально встречается в тексте документа (issue #509:
    после фикса значения сверяются с текстом, а не просто пропускаются насквозь)."""
    doc_text = "Общий анализ крови. Гемоглобин: 155 г/л. Заключение: аллергия на амоксициллин."
    payload = {"date": "2026-07-10", "values": {"Hb": 155}, "allergies": ["амоксициллин"], "conditions": []}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")
    assert out["values"] == {"Hb": 155}
    assert out["allergies"] == ["амоксициллин"]


# ── issue #509: не выдумывать названия показателей по нечитаемому тексту ────


@pytest.mark.asyncio
async def test_text_plain_drops_values_whose_label_is_not_in_document_text():
    """Регрессия #509: PDF с нечитаемыми названиями (дефект шрифта — только точки

    и числа), где модель всё равно вернула правдоподобный, но выдуманный список
    названий. Ни один показатель не должен пройти — названий в тексте нет."""
    # Реальный вывод PyMuPDF для PDF, где кириллица набрана шрифтом без глифов
    # (репро воспроизведено вживую перед фиксом, см. отчёт по issue #509).
    doc_text = (
        "·········· ······· ·····\n"
        "····: 20.09.2026\n"
        "·······: 5.4 ·····/·\n"
        "·········: 88 ······/·\n"
        "····· ··········: 5.9 ·····/·\n"
        "····: 3.8 ·····/·\n"
        "···: 27 ··/·"
    )
    payload = {
        "date": "2026-09-20",
        "laboratory": None,
        "values": {
            "glucose": 5.4,
            "insulin": 88,  # в документе на самом деле креатинин
            "HbA1c": 5.9,  # в документе на самом деле общий холестерин
            "cholesterol_total": 3.8,  # в документе на самом деле ЛПНП
            "HDL": 27,  # в документе на самом деле АЛТ
        },
        "allergies": [],
        "conditions": [],
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == {}
    assert set(out["_unverified_labels"]) == {"glucose", "insulin", "HbA1c", "cholesterol_total", "HDL"}


@pytest.mark.asyncio
async def test_text_plain_keeps_only_verified_values_partial_match():
    """Если часть названий реально читается в тексте, а часть — нет, оставляем

    только подтверждённые (не всё-или-ничего)."""
    doc_text = "Биохимический анализ крови. Глюкоза: 5.4 ммоль/л. ....: 88 ....../."
    payload = {"values": {"glucose": 5.4, "insulin": 88}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == {"glucose": 5.4}
    assert out["_unverified_labels"] == ["insulin"]


@pytest.mark.asyncio
async def test_image_path_not_verified_against_text():
    """Vision-путь (фото/скан без текстового слоя) не имеет текста документа для

    сверки — значения не должны фильтроваться, иначе сломаем нормальный разбор
    фотографий (issue #509, ограничение п.3)."""
    payload = {"values": {"glucose": 5.4, "insulin": 88}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"jpeg-bytes-not-real-text", "image/jpeg")

    assert out["values"] == {"glucose": 5.4, "insulin": 88}
    assert "_unverified_labels" not in out


@pytest.mark.asyncio
async def test_text_plain_normal_document_fully_parsed():
    """Обычный читаемый документ по-прежнему разбирается полностью — фикс не

    должен ломать штатный путь, только защищать от галлюцинаций на битом тексте."""
    doc_text = (
        "Результаты анализа крови от 20.09.2026\n"
        "Глюкоза: 5.4 ммоль/л\n"
        "Креатинин: 88 мкмоль/л\n"
        "Общий холестерин: 5.9 ммоль/л\n"
        "ЛПНП: 3.8 ммоль/л\n"
        "АЛТ: 27 Ед/л\n"
    )
    payload = {
        "date": "2026-09-20",
        "values": {
            "glucose": 5.4,
            "creatinine": 88,
            "cholesterol_total": 5.9,
            "LDL": 3.8,
            "ALT": 27,
        },
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == payload["values"]
    assert "_unverified_labels" not in out
