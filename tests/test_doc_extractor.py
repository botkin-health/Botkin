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


def _fake_response_text(text: str) -> dict:
    """Ответ Anthropic с произвольным текстом (не обязательно чистым JSON)."""
    return {"content": [{"type": "text", "text": text}]}


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
    call = AsyncMock(return_value=_fake_response(payload))
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    # Ни одного выдуманного показателя в карту. Модель на нечитаемом тексте
    # больше не вызывается вовсе (гейт стоит ДО вызова), так что и выдумать
    # ей нечего — поэтому отброшенных значений тоже нет, а флаг выставлен.
    assert out["values"] == {}
    assert out["_unreadable_text"] is True
    call.assert_not_called()


@pytest.mark.asyncio
async def test_readable_document_values_never_dropped_by_label_registry(caplog):
    """Читаемый документ: значения НЕ отбрасываются, даже если название не
    найдено в тексте по реестру синонимов, — расхождение только логируется.

    Построчная сверка хрупка (перестановка слов, латиница/кириллица, перенос
    строки): независимое ревью #509 показало 2 из 8 на обычном бланке, среди
    выброшенных — ALP для phenoage. Тихая потеря настоящего анализа хуже."""
    doc_text = (
        "Белок общий 72 г/л\nФосфатаза щелочная (ALP) 95 Ед/л\n"
        "C-реактивный белок 2.1 мг/л\nВитамин В12 410 пг/мл\nКреатинин 88 мкмоль/л\n"
        "Гликированный\nгемоглобин 5.9 %"
    )
    values = {"total_protein": 72, "ALP": 95, "CRP": 2.1, "vitamin_B12": 410, "creatinine": 88, "HbA1c": 5.9}
    payload = {"values": dict(values)}
    with caplog.at_level("INFO"):
        with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
            out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == values
    assert "_unverified_labels" not in out


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


# ── ревью #509: реестр не должен терять реальные данные вне своего покрытия ──


@pytest.mark.asyncio
async def test_readable_document_with_out_of_registry_keys_keeps_all_values():
    """Ретроспектива ревью: реестр `MARKER_LABELS` покрывает 70 из 729 реальных

    ключей `blood_tests.values` на проде. Ключ вне реестра (`Ht`, `lymphocytes_pct`,
    `chloride`, `urine_pH`, ...) должен пройти как есть на полностью читаемом
    документе — иначе фикс #509 превращается в тихую потерю настоящих анализов
    (первая версия фикса теряла 11 из 11 именно на таком наборе)."""
    doc_text = (
        "Общий анализ крови с лейкоформулой и биохимией\n"
        "Гематокрит: 42 %\n"
        "Лимфоциты: 32 %\n"
        "Эозинофилы: 3 %\n"
        "Моноциты: 6 %\n"
        "Альбумин: 44 г/л\n"
        "Хлор: 103 ммоль/л\n"
        "Холестерин: 5.1 ммоль/л\n"
        "Витамин D (25-OH): 34 нг/мл\n"
        "Т4 свободный: 15.8 пмоль/л\n"
        "pH: 6.0\n"
        "Относительная плотность: 1.018\n"
    )
    values = {
        "Ht": 42,
        "lymphocytes_pct": 32,
        "eosinophils_pct": 3,
        "monocytes_pct": 6,
        "albumin": 44,
        "chloride": 103,
        "cholesterol": 5.1,
        "vitamin_d": 34,
        "fT4": 15.8,
        "urine_pH": 6.0,
        "urine_density": 1.018,
    }
    payload = {"date": "2026-09-20", "values": values}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == values, f"потеряно: {set(values) - set(out['values'])}"
    assert "_unverified_labels" not in out


@pytest.mark.asyncio
async def test_registry_lookup_is_case_insensitive():
    """`vitamin_d`/`vitamin_D` и `fT4`/`FT4` — один и тот же маркер по разным

    источникам KB (см. core.health.kb_schema для похожей проблемы) — сверка
    должна находить запись реестра независимо от регистра ключа."""
    doc_text = "Витамин D (25-OH): 34 нг/мл. Т4 свободный: 15.8 пмоль/л."
    payload = {"values": {"vitamin_d": 34, "fT4": 15.8}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == {"vitamin_d": 34, "fT4": 15.8}
    assert "_unverified_labels" not in out


@pytest.mark.asyncio
async def test_known_limitation_hallucination_on_readable_text_is_logged_not_dropped(caplog):
    """ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ (осознанный компромисс, ревью #509).

    Текст читается, а модель приписала числу название другого показателя
    (документ — креатинин, ответ — инсулин). Программно это больше НЕ
    отсекается: отсев по реестру давал частые ложные срабатывания на настоящих
    анализах. На читаемом тексте защита — инструкция модели + лог расхождения.
    Исходный инцидент #509 был на НЕЧИТАЕМОМ тексте — его ловит документный гейт.
    Тест фиксирует поведение, чтобы снятую защиту не принимали за действующую."""
    doc_text = "Биохимический анализ крови от 20.09.2026\nКреатинин: 88 мкмоль/л\n"
    payload = {"date": "2026-09-20", "values": {"insulin": 88}}
    with caplog.at_level("INFO"):
        with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
            out = await doc_extractor.extract_medical_data(doc_text.encode(), "text/plain")

    assert out["values"] == {"insulin": 88}
    assert any("insulin" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_unreadable_text_flag_set_even_when_model_returns_nothing():
    """E2E 23.09.2026: на битом PDF модель сама вернула пустой values — гейт
    отбрасывал ноль значений, _unverified_labels был пуст, и пользователь
    получал общее «не нашёл данных» вместо честного «текст читается плохо»."""
    broken = "···········\n·······: 5.4 ·····/·\n·········: 88 ······/·"
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response({"values": {}}))):
        out = await doc_extractor.extract_medical_data(broken.encode(), "text/plain")

    assert out["values"] == {}
    assert out.get("_unreadable_text") is True


def test_parse_response_tolerates_text_after_json():
    """E2E 23.09.2026: модель дописала пояснение после JSON — строгий
    json.loads падал с «Extra data», разбор молча становился «не нашёл данных».
    Критично для НОРМАЛЬНЫХ документов: так терялся бы весь разбор."""
    text = '{"date": "2026-09-20", "values": {"glucose": 5.4}}\\n\\nПримечание: показатель в норме.'
    assert doc_extractor._parse_response(_fake_response_text(text))["values"] == {"glucose": 5.4}


def test_parse_response_tolerates_code_fence_and_trailing_text():
    text = '```json\\n{"values": {"ALT": 27}}\\n```\\nЕсли нужно — уточню.'
    assert doc_extractor._parse_response(_fake_response_text(text))["values"] == {"ALT": 27}


def test_parse_response_tolerates_preamble():
    text = 'Вот данные из документа:\\n{"values": {"Hb": 141}}'
    assert doc_extractor._parse_response(_fake_response_text(text))["values"] == {"Hb": 141}


def test_parse_response_returns_empty_without_json():
    assert doc_extractor._parse_response(_fake_response_text("Текст нечитаем.")) == {}


@pytest.mark.asyncio
async def test_unreadable_text_does_not_call_model():
    """Гейт читаемости до вызова модели: битый текст — ни вызова модели,
    ни шанса на выдумку или нераспарсенный ответ; флаг выставлен."""
    broken = "···········\\n·······: 5.4 ·····/·\\n·········: 88 ······/·"
    call = AsyncMock()
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data(broken.encode(), "text/plain")
    call.assert_not_called()
    assert out["values"] == {}
    assert out["_unreadable_text"] is True


# ── #558 фаза 1: дата взятия материала, а не дата печати ────────────────────


def test_prompt_prioritises_sampling_date_over_print_date():
    prompt = doc_extractor._SYSTEM_PROMPT
    assert "Дата взятия материала" in prompt
    assert "Дата печати" in prompt
    assert "date_label" in prompt


@pytest.mark.asyncio
async def test_print_date_is_rejected():
    payload = {"date": "2026-09-24", "date_label": "Дата печати", "values": {"Hb": 119}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["date"] is None
    assert out["_date_rejected"] == "print_or_issue_date"
    assert out["values"] == {"Hb": 119}


@pytest.mark.asyncio
async def test_future_date_is_rejected():
    payload = {"date": "2028-09-13", "date_label": "Дата приема", "values": {}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["date"] is None
    assert out["_date_rejected"] == "future"


@pytest.mark.asyncio
async def test_non_iso_date_is_dropped():
    payload = {"date": "13.09.2026", "values": {}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["date"] is None
    assert out["_date_rejected"] == "not_iso"


@pytest.mark.asyncio
async def test_sampling_date_kept_with_label():
    payload = {"date": "2026-09-13", "date_label": "Дата взятия материала", "values": {"Hb": 119}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["date"] == "2026-09-13"
    assert out["date_label"] == "Дата взятия материала"
    assert "_date_rejected" not in out


@pytest.mark.asyncio
async def test_response_with_leading_thinking_block_is_parsed():
    """Sonnet 5 может прислать перед ответом блок thinking — разбор не должен срываться (#558)."""
    response = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": json.dumps({"date": "2026-08-11", "values": {}, "conditions": ["Акне (L70.0)"]})},
        ]
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=response)):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["date"] == "2026-08-11"
    assert out["conditions"] == ["Акне (L70.0)"]


# ── #558 фаза 2: тип документа, название и резюме ───────────────────────────


def test_prompt_describes_doc_kind_summary_and_doc_type():
    prompt = doc_extractor._SYSTEM_PROMPT
    for token in ("doc_kind", "smear_pcr", "lab_panel", "summary", "doc_type"):
        assert token in prompt


@pytest.mark.asyncio
async def test_smear_values_are_dropped_and_summary_kept():
    payload = {
        "date": "2026-09-08",
        "doc_kind": "smear_pcr",
        "doc_type": "Мазок и флороценоз",
        "summary": "Лейкоциты 1–2 в п/зр; Gardnerella не обнаружена.",
        "values": {"leukocytes": 50000, "WBC": 1.2},
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["values"] == {}
    assert out["_dropped_values"] == {"leukocytes": 50000, "WBC": 1.2}
    assert out["summary"].startswith("Лейкоциты")
    assert out["doc_type"] == "Мазок и флороценоз"


@pytest.mark.asyncio
async def test_lab_panel_values_kept_and_unknown_kind_becomes_other():
    lab = {"date": "2026-09-13", "doc_kind": "LAB_PANEL", "values": {"Hb": 119}}
    odd = {"date": "2026-09-13", "doc_kind": "questionnaire", "values": {}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(lab))):
        out_lab = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(odd))):
        out_odd = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out_lab["doc_kind"] == "lab_panel" and out_lab["values"] == {"Hb": 119}
    assert out_odd["doc_kind"] == "other"


@pytest.mark.asyncio
async def test_missing_doc_kind_left_absent_for_legacy_readers():
    payload = {"date": "2026-09-13", "values": {"Hb": 119}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert "doc_kind" not in out
    assert out["values"] == {"Hb": 119}


# ── #558 фаза 3: коды Z (обращения, осмотры) — не диагнозы ─────────────────


def test_prompt_forbids_z_codes_in_conditions():
    assert "Z00–Z99" in doc_extractor._SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_z_codes_filtered_real_diagnoses_kept():
    payload = {
        "values": {},
        "conditions": [
            "Гинекологическое обследование (общее) (рутинное) (Z01.4)",
            "Угри обыкновенные (L70.0)",
            "Изменения окраски волос (L67.1)",
            "Наблюдение Z34",
        ],
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["conditions"] == ["Угри обыкновенные (L70.0)", "Изменения окраски волос (L67.1)"]
    assert len(out["_dropped_conditions"]) == 2


@pytest.mark.asyncio
async def test_word_with_letter_z_is_not_a_z_code():
    payload = {"values": {}, "conditions": ["Синдром Золлингера-Эллисона (E16.4)", "Zinc deficiency (E60)"]}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert len(out["conditions"]) == 2
    assert "_dropped_conditions" not in out


# ── #558 фаза 4: активный B12 и единицы ─────────────────────────────────────


def test_holotranscobalamin_is_separate_canonical_marker():
    from core.health.kb_schema import to_canonical

    canon, _ = to_canonical({"holotranscobalamin": 138.3, "vitamin_B12": 400})
    assert canon["holotranscobalamin"] == 138.3
    assert canon["vitamin_B12"] == 400


def test_prompt_separates_active_b12_and_asks_units():
    prompt = doc_extractor._SYSTEM_PROMPT
    assert "холотранскобаламин" in prompt
    assert '"units"' in prompt


@pytest.mark.asyncio
async def test_crp_in_mg_dl_converted_to_mg_l():
    payload = {
        "values": {"hs_CRP": 0.07, "ferritin": 15.78},
        "units": {"hs_CRP": "мг/дл", "ferritin": "нг/мл"},
    }
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        out = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out["values"]["hs_CRP"] == pytest.approx(0.7)
    assert out["units"]["hs_CRP"] == "мг/л"
    assert out["values"]["ferritin"] == 15.78
    assert out["_unit_conversions"] == ["hs_CRP: мг/дл → мг/л ×10"]


@pytest.mark.asyncio
async def test_crp_already_mg_l_and_latin_unit_variants():
    same = {"values": {"CRP": 3.0}, "units": {"CRP": "мг/л"}}
    latin = {"values": {"CRP": 0.3}, "units": {"CRP": "mg/dL"}}
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(same))):
        out_same = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(latin))):
        out_latin = await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    assert out_same["values"]["CRP"] == 3.0 and "_unit_conversions" not in out_same
    assert out_latin["values"]["CRP"] == pytest.approx(3.0)
