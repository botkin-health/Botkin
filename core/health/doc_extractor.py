# core/health/doc_extractor.py
"""Извлечение медицинских данных из документов через Anthropic Claude."""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from config.models import DOC_EXTRACT_MODEL
from config.settings import get_settings
from core.health.doc_marker_labels import split_verified_values
from core.health.doc_readability import is_document_text_readable
from core.health.kb_schema import CANONICAL

logger = logging.getLogger(__name__)

_MODEL = DOC_EXTRACT_MODEL
_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_SYSTEM_PROMPT_TEMPLATE = """Ты — медицинский парсер. Твоя задача: извлечь структурированные данные из медицинского документа.

Верни ТОЛЬКО валидный JSON объект без markdown-обёртки. Структура:
{{
  "date": "ГГГГ-ММ-ДД или null",
  "date_label": "подпись рядом с выбранной датой, как напечатано, или null",
  "laboratory": "название лаборатории или null",
  "doc_kind": "lab_panel | imaging | smear_pcr | doctor_note | other",
  "doc_type": "короткое название документа по-русски или null",
  "summary": "1–4 предложения по-русски о том, что показал документ, или null",
  "values": {{
    "ключ": числовое_значение,
    ...
  }},
  "units": {{
    "ключ": "единица измерения, как напечатана на бланке",
    ...
  }},
  "allergies": ["строка", ...],
  "conditions": ["строка", ...]
}}

Правила:
- "date" — дата, когда сделано исследование или приём. Бери дату с подписью «Дата взятия материала», «Дата забора», «Дата исследования», «Дата приема», «Дата визита» (в таком порядке приоритета). НИКОГДА не бери «Дата печати», «Дата выдачи», «Дата регистрации», «Дата готовности», «Дата рождения» — на бланках лабораторий они часто стоят рядом с датой взятия и позже её на дни и недели. Если на странице нет даты исследования (например, это продолжение документа) — null. На бланке дата обычно ДД.ММ.ГГГГ — переведи в ГГГГ-ММ-ДД и внимательно проверь год.
- "date_label" — подпись, стоящая рядом с выбранной датой, дословно (например «Дата взятия материала»); null, если date null.
- "doc_kind" — тип документа: "lab_panel" — количественные анализы крови и мочи, биохимия, гормоны, витамины, микроэлементы; "imaging" — УЗИ, МРТ, КТ, рентген, ЭКГ, ЭхоКГ; "smear_pcr" — мазки, цитология, ПЦР, ВПЧ, посевы, флороценоз; "doctor_note" — приём, заключение или выписка врача; "other" — анкеты, направления, преаналитика и всё остальное.
- "doc_type" — короткое название, как назвал бы документ врач: «Общий анализ крови», «УЗИ почек», «ПЦР на ВПЧ», «Заключение дерматолога».
- "summary" — что показал документ, только то, что в нём напечатано: результаты, включая качественные («не обнаружено», «1–2 в п/зр»), и заключение/рекомендации врача, если есть. Без советов и интерпретаций от себя. НЕ пиши от себя оценок «в пределах нормы», «всё в порядке», «повышен» — только то, что напечатано на бланке: значение, референс и пометку лаборатории («+», «↑», «H», «*»), если она есть. Разные рекомендации не сливай в одну фразу — перечисли каждую отдельно, как в документе. Для "lab_panel" — null: значения уже в "values".
- Для "smear_pcr" поле "values" ВСЕГДА пустое {{}}: результаты мазков и ПЦР качественные или условные («не обнаружено», «1–2 в п/зр», «> 50000», «7×10⁶») — их пиши в "summary", а не в "values".
- "values" — только числовые показатели (анализы крови, биохимия, гормоны, витамины, размеры органов в УЗИ и т.д.)
- Используй короткие английские ключи. Если показатель есть в этом списке — используй ИМЕННО это имя: {canonical_keys}. Если показателя в списке нет — придумай короткий английский ключ сам.
- Не включай единицы измерения в значения — только число; единицу каждого показателя, как она напечатана на бланке (мг/дл, мг/л, пмоль/л…), положи в "units" под тем же ключом.
- Показатели мочи (общий анализ мочи, суточная моча) — ключи с суффиксом "_urine" (например "calcium_urine", "creatinine_urine", "protein_urine"), НИКОГДА не ключи показателей крови ("creatinine", "calcium", "glucose"): креатинин мочи 9000 мкмоль/л под ключом крови выглядит как почечная недостаточность.
- «Витамин B12 активный» / «холотранскобаламин» — ключ "holotranscobalamin", НЕ "vitamin_B12": это другой анализ с другой нормой. "vitamin_B12" — только общий витамин B12.
- "allergies" — список аллергий/непереносимостей, указанных в документе (аллергены, вещества, продукты). Строки на языке документа. Пусто [] если нет.
- "conditions" — список хронических/персистирующих диагнозов из документа, с кодом МКБ если он есть (например "Бронхиальная астма (J45.0)"). Пусто [] если нет. Только заболевания: НЕ включай коды Z00–Z13 (осмотры, обследования, скрининг — например «Z01.4 гинекологическое обследование»), цели визита и формулировки вроде «здорова». Значимые состояния с кодом Z (стент, трансплантат, диализ, беременность, длительный приём препарата) — включай.
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

    # 180 с: Sonnet 5 + thinking + до 4096 токенов ответа не укладывается в 60 с на
    # плотной странице, а тайм-аут = потерянный документ (ревью #560).
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            _ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                # Резюме + до ~30 показателей + блок thinking у Sonnet 5 (он тоже тратит
                # этот лимит). Обрезанный JSON = потерянный документ (#558).
                "max_tokens": 4096,
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
        elif parsed > (today or date.today()) + timedelta(days=1):
            # +1 день: сервер в UTC, а у пользователя в Москве/Израиле уже «завтра».
            reason = "future"
        else:
            data["date"] = parsed.isoformat()
            return
    logger.info("doc_extractor: дата %r (подпись %r) отброшена: %s", raw, data.get("date_label"), reason)
    data["date"] = None
    data["_date_rejected"] = reason


DOC_KINDS = ("lab_panel", "imaging", "smear_pcr", "doctor_note", "other")


def _normalize_kind(data: dict) -> None:
    """Приводит doc_kind/doc_type/summary; у мазков и ПЦР отбрасывает числа (#558).

    Числа мазков («1–2 в п/зр», «> 50000») не являются измерениями — модель
    выдумывает под них ключи вроде `leukocytes`, а может назвать и `WBC`.
    Отброшенное остаётся в `_dropped_values` для логов. Нет doc_kind в ответе —
    поле не добавляем (старые записи и читатели без него работают как раньше).
    """
    raw_kind = data.get("doc_kind")
    if raw_kind is not None:
        kind = re.sub(r"[\s\-]+", "_", str(raw_kind).strip().lower())
        if kind in DOC_KINDS:
            data["doc_kind"] = kind
        else:
            # Незнакомый тип ≠ «other»: other не пишется в blood_tests, и настоящая
            # панель с опечаткой в типе молча пропала бы из динамики (ревью #560).
            logger.info("doc_extractor: незнакомый doc_kind %r — поле убрано", raw_kind)
            data.pop("doc_kind")
    for key in ("doc_type", "summary"):
        if key in data:
            text = str(data.get(key) or "").strip()
            data[key] = text or None
    if data.get("doc_kind") == "lab_panel" and data.get("summary"):
        # Резюме анализов от модели не храним: она регулярно пишет «все показатели в
        # пределах нормы» при значениях выше нормы (кальций 1.33 при норме до 1.32,
        # RBC 6.18 при норме до 5.70), и никакой фильтр фраз её не догоняет — каждая
        # новая формулировка проходит. Значения лежат рядом, оценка — дело агента по
        # референсам. У УЗИ/мазков/заключений резюме — пересказ вывода врача (#558).
        data["summary"] = None
    values = data.get("values")
    if data.get("doc_kind") == "smear_pcr" and isinstance(values, dict) and values:
        logger.info("doc_extractor: у smear_pcr отброшены числа: %s", list(values))
        data["_dropped_values"] = values
        data["values"] = {}


# Z00–Z13 — обращения для осмотра, обследования, скрининга: не диагнозы, в медпрофиль
# не попадают (#558). Остальные Z — значимые состояния (Z95 стент, Z94 трансплантат,
# Z99.2 диализ, Z21 ВИЧ, Z34 беременность, Z79 длительная терапия) — их оставляем.
_Z_CODE_RE = re.compile(r"\bZ(?:0\d|1[0-3])(?:\.\d+)?\b")


def _filter_conditions(data: dict) -> None:
    """Убирает из conditions пункты с кодом Z00–Z13; убранное — в `_dropped_conditions`."""
    kept, dropped = [], []
    for item in data.get("conditions") or []:
        (dropped if _Z_CODE_RE.search(item) else kept).append(item)
    if dropped:
        logger.info("doc_extractor: коды Z убраны из диагнозов: %s", dropped)
        data["_dropped_conditions"] = dropped
    data["conditions"] = kept


# Известные несовпадения единицы бланка с канонической (kb_schema): (ключ, единица
# бланка без пробелов, casefold) → (множитель, каноническая единица). Только то, что
# встречалось на реальных бланках; незнакомое не «чиним» молча (#558).
# Ключи — в casefold: модель пишет и hs_CRP, и hsCRP, и crp.
_UNIT_CONVERSIONS: dict[tuple[str, str], tuple[float, str]] = {
    (key, unit): (10.0, "мг/л") for key in ("hs_crp", "hscrp", "crp") for unit in ("мг/дл", "mg/dl")
}


def _convert_units(data: dict) -> None:
    """Пересчитывает значения, напечатанные не в канонической единице (СРБ в мг/дл).

    Сделанные пересчёты — в `_unit_conversions`, `units[key]` обновляется на
    каноническую единицу, чтобы повторная обработка не умножила ещё раз.
    """
    values, units = data.get("values"), data.get("units")
    if not isinstance(values, dict) or not isinstance(units, dict):
        return
    done = []
    for key, unit in list(units.items()):
        norm = "".join(str(unit).split()).casefold()
        rule = _UNIT_CONVERSIONS.get((str(key).casefold(), norm))
        raw = values.get(key)
        if rule is None or not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        factor, canon_unit = rule
        values[key] = round(raw * factor, 6)
        units[key] = canon_unit
        done.append(f"{key}: {unit} → {canon_unit} ×{factor:g}")
    if done:
        logger.info("doc_extractor: пересчёт единиц: %s", done)
        data["_unit_conversions"] = done


def _as_str_list(v) -> list[str]:
    """Безопасно привести значение к списку непустых строк. Не-список → []."""
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


async def extract_medical_data(file_bytes: bytes, mime_type: str, user_id: Optional[int] = None) -> dict[str, Any]:
    """Извлекает медицинские данные из документа через Claude.

    Args:
        file_bytes: байты файла (PDF или изображение)
        mime_type: MIME-тип файла
        user_id: владелец документа — для учёта расходов в llm_usage_log

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
        try:
            from core.llm_usage import log_anthropic_response

            log_anthropic_response(purpose="doc_extract", model=_MODEL, response_json=response, user_id=user_id)
        except Exception:
            logger.exception("doc_extractor: учёт расходов не записался")
        if response.get("stop_reason") == "max_tokens":
            logger.warning("doc_extractor: ответ обрезан по max_tokens — JSON может не разобраться (%s)", mime_type)
        data = _parse_response(response)
        if data:
            _sanitize_date(data)
            _normalize_kind(data)
            _convert_units(data)
            data["allergies"] = _as_str_list(data.get("allergies"))
            data["conditions"] = _as_str_list(data.get("conditions"))
            _filter_conditions(data)
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
