# core/health/doc_extractor.py
"""Извлечение медицинских данных из документов через Anthropic Claude."""

from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import Any, Optional

import httpx

from config.settings import get_settings
from core.health.doc_marker_labels import split_verified_values
from core.health.doc_readability import is_document_text_readable
from core.health.kb_schema import CANONICAL

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_SYSTEM_PROMPT_TEMPLATE = """Ты — медицинский парсер. Твоя задача: извлечь структурированные данные из медицинского документа.

Верни ТОЛЬКО валидный JSON объект без markdown-обёртки. Структура:
{{
  "date": "ГГГГ-ММ-ДД или null",
  "date_label": "подпись рядом с выбранной датой, как напечатано, или null",
  "laboratory": "название лаборатории или null",
  "values": {{
    "ключ": числовое_значение,
    ...
  }},
  "allergies": ["строка", ...],
  "conditions": ["строка", ...]
}}

Правила:
- "date" — дата, когда сделано исследование или приём. Бери дату с подписью «Дата взятия материала», «Дата забора», «Дата исследования», «Дата приема», «Дата визита» (в таком порядке приоритета). НИКОГДА не бери «Дата печати», «Дата выдачи», «Дата регистрации», «Дата готовности», «Дата рождения» — на бланках лабораторий они часто стоят рядом с датой взятия и позже её на дни и недели. Если на странице нет даты исследования (например, это продолжение документа) — null. На бланке дата обычно ДД.ММ.ГГГГ — переведи в ГГГГ-ММ-ДД и внимательно проверь год.
- "date_label" — подпись, стоящая рядом с выбранной датой, дословно (например «Дата взятия материала»); null, если date null.
- "values" — только числовые показатели (анализы крови, биохимия, гормоны, витамины, размеры органов в УЗИ и т.д.)
- Используй короткие английские ключи. Если показатель есть в этом списке — используй ИМЕННО это имя: {canonical_keys}. Если показателя в списке нет — придумай короткий английский ключ сам.
- Не включай единицы измерения в значения — только число
- "allergies" — список аллергий/непереносимостей, указанных в документе (аллергены, вещества, продукты). Строки на языке документа. Пусто [] если нет.
- "conditions" — список хронических/персистирующих диагнозов из документа, с кодом МКБ если он есть (например "Бронхиальная астма (J45.0)"). Пусто [] если нет.
- Не придумывай данных, которых нет в документе. Если чего-то нет — пустой список/пустой values.
- КРИТИЧНО: название показателя в "values" бери ТОЛЬКО если оно реально прочитано в документе (напечатано рядом с числом). НИКОГДА не достраивай название по типичному составу панели, по порядку строк или по догадке о том, какой это может быть анализ. Если текст рядом с числом нечитаем, повреждён или отсутствует (например, вместо букв — точки, кракозябры, пустые места) — этот показатель в "values" НЕ включай вообще, даже если число само по себе читается чётко. Число без надёжно прочитанного названия хуже, чем отсутствие числа: неверно приписанное название — это другой анализ с другой нормой.
- Если весь документ или его часть нечитаемы (повреждённый шрифт, плохое качество скана) — так и работай: верни только те показатели, названия которых ты действительно прочитал, а остальное не выдумывай."""


def _build_system_prompt() -> str:
    """Собирает системный промпт со списком канонических ключей из реестра.

    Строится один раз при импорте модуля (см. `_SYSTEM_PROMPT` ниже) — реестр
    `CANONICAL` статичен на время жизни процесса, пересобирать на каждый вызов
    незачем. Список ключей — не алиасов: модель должна называть показатель так,
    как его ждёт `core.health.kb_schema.to_canonical` при матчинге.
    """
    canonical_keys = ", ".join(CANONICAL.keys())
    return _SYSTEM_PROMPT_TEMPLATE.format(canonical_keys=canonical_keys)


# Модуль-level константа для существующих вызывающих (см. `_call_anthropic`).
# Строится лениво при импорте — CANONICAL к этому моменту уже полностью собран.
_SYSTEM_PROMPT = _build_system_prompt()


async def _call_anthropic(messages: list[dict]) -> dict:
    """Вызов Anthropic Messages API."""
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY не настроен")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 1024,
                "system": _SYSTEM_PROMPT,
                "messages": messages,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _build_image_message(file_bytes: bytes, mime_type: str) -> dict:
    """Собирает Anthropic-сообщение с base64-изображением."""
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": b64},
            },
            {"type": "text", "text": "Извлеки медицинские данные из этого документа."},
        ],
    }


def _build_text_message(file_bytes: bytes) -> dict:
    """Собирает Anthropic-сообщение из уже извлечённого текста документа (text-блок).

    Используется для PDF с текстовым слоем: текст извлекается в вызывающем коде и
    приходит сюда байтами. Раньше такой вход ошибочно паковался в image-блок с
    media_type=text/plain, который Anthropic отклоняет (см. #319)."""
    doc_text = file_bytes.decode("utf-8", errors="replace")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": doc_text},
            {"type": "text", "text": "Извлеки медицинские данные из этого документа."},
        ],
    }


def _build_pdf_message(file_bytes: bytes) -> dict:
    """Собирает Anthropic-сообщение с base64 PDF (document source)."""
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return {
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            },
            {"type": "text", "text": "Извлеки медицинские данные из этого документа."},
        ],
    }


def _parse_response(response: dict) -> dict[str, Any]:
    """Парсит ответ Claude в dict. Возвращает {} при любой ошибке.

    Берём ПЕРВЫЙ JSON-объект в ответе и игнорируем текст до и после него.
    Строгий json.loads падал с «Extra data», когда модель дописывала пояснение
    после JSON (или после закрывающего ```), — разбор тогда молча превращался в
    «не нашёл данных» (E2E 23.09.2026).
    """
    try:
        # Текстовые блоки, где бы они ни стояли: Sonnet 5 может начать ответ с
        # блока thinking, и content[0]["text"] тогда падал KeyError (#558).
        text = "".join(b["text"] for b in response["content"] if isinstance(b, dict) and "text" in b)
    except Exception as e:
        logger.warning("doc_extractor: неожиданная форма ответа Claude: %s", e)
        return {}
    start = text.find("{")
    if start == -1:
        logger.warning("doc_extractor: в ответе Claude нет JSON-объекта: %r", text[:200])
        return {}
    try:
        data, _end = json.JSONDecoder().raw_decode(text[start:])
    except ValueError as e:
        logger.warning("doc_extractor: не удалось распарсить ответ Claude: %s; начало: %r", e, text[:200])
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# Подписи дат, которые не являются датой исследования (#558): на бланках КДЛ
# «Дата печати» стоит рядом с «Датой взятия материала» и позже неё на дни.
_NON_STUDY_DATE_LABELS = ("печат", "выдач", "регистрац", "готов", "рожден")


def _sanitize_date(data: dict, today: Optional[date] = None) -> None:
    """Проверяет `date` ответа модели на месте; неподходящую — обнуляет.

    Причина отказа — в `_date_rejected` (для логов и превью): not_iso,
    print_or_issue_date (модель сама подписала дату как печать/выдачу), future.
    Дату не угадываем и не чиним — только отказываемся от явно неверной.
    """
    raw = data.get("date")
    if raw is None:
        return
    label = str(data.get("date_label") or "").casefold()
    try:
        parsed = date.fromisoformat(str(raw).strip())
    except ValueError:
        reason = "not_iso"
    else:
        if any(marker in label for marker in _NON_STUDY_DATE_LABELS):
            reason = "print_or_issue_date"
        elif parsed > (today or date.today()):
            reason = "future"
        else:
            data["date"] = parsed.isoformat()
            return
    logger.info("doc_extractor: дата %r (подпись %r) отброшена: %s", raw, data.get("date_label"), reason)
    data["date"] = None
    data["_date_rejected"] = reason


def _as_str_list(v) -> list[str]:
    """Безопасно привести значение к списку непустых строк. Не-список → []."""
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


async def extract_medical_data(file_bytes: bytes, mime_type: str) -> dict[str, Any]:
    """Извлекает медицинские данные из документа через Claude.

    Args:
        file_bytes: байты файла (PDF или изображение)
        mime_type: MIME-тип файла

    Returns:
        dict с ключами date, laboratory, values (или пустой dict если не нашёл)
    """
    try:
        # Гейт читаемости (issue #509) — ДО вызова модели. Если в текстовом слое
        # по сути нет букв (шрифт без нужных глифов), прочитать названия
        # показателей нельзя в принципе: модель тут может только выдумать их или
        # вернуть ответ, который не распарсится. Раньше гейт стоял после разбора
        # и не срабатывал, когда разбор падал (E2E 23.09.2026). Заодно не платим
        # за заведомо бесполезный вызов.
        if mime_type == "text/plain":
            doc_text = file_bytes.decode("utf-8", errors="replace")
            if not is_document_text_readable(doc_text):
                logger.warning("doc_extractor: текст документа нечитаем (нет слов) — модель не вызываем")
                return {
                    "date": None,
                    "laboratory": None,
                    "values": {},
                    "allergies": [],
                    "conditions": [],
                    "_unverified_labels": [],
                    "_unreadable_text": True,
                }

        if mime_type == "application/pdf":
            message = _build_pdf_message(file_bytes)
        elif mime_type == "text/plain":
            message = _build_text_message(file_bytes)
        else:
            message = _build_image_message(file_bytes, mime_type)

        response = await _call_anthropic([message])
        data = _parse_response(response)
        if data:
            _sanitize_date(data)
            data["allergies"] = _as_str_list(data.get("allergies"))
            data["conditions"] = _as_str_list(data.get("conditions"))
            # Без проверки «values непуст»: гейт читаемости должен срабатывать и
            # тогда, когда модель сама вернула пустой список, — именно этот
            # случай пользователю надо честно объяснить (E2E 23.09.2026).
            if mime_type == "text/plain" and isinstance(data.get("values"), dict):
                # Программные проверки (issue #509) доступны только здесь, где
                # file_bytes — РЕАЛЬНЫЙ текст документа (текстовый слой PDF,
                # извлечённый локально через PyMuPDF в вызывающем коде), а не то,
                # что вернула модель. Для image/pdf-без-текстового-слоя (vision)
                # сверять не с чем — там защита только на уровне промпта выше.
                #
                # Читаемость уже проверена до вызова модели (см. начало функции).
                # Здесь — только сверка по реестру синонимов, и она ТОЛЬКО
                # диагностика, ничего не отбрасывает: построчный поиск по реальным
                # бланкам хрупок («Белок общий» vs «общий белок», латинская C vs
                # кириллическая С, перенос строки). Независимое ревью #509 — 2 из 8
                # на обычном бланке, среди выброшенных ALP для phenoage.
                doc_text = file_bytes.decode("utf-8", errors="replace")
                _verified, unconfirmed = split_verified_values(data["values"], doc_text)
                if unconfirmed:
                    logger.info(
                        "doc_extractor: название не найдено в тексте документа (значение сохранено): %s",
                        unconfirmed,
                    )
        return data
    except Exception as e:
        logger.error("doc_extractor: ошибка извлечения: %s", e)
        return {}
