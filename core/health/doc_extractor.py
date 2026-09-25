# core/health/doc_extractor.py
"""Извлечение медицинских данных из документов через Anthropic Claude."""

from __future__ import annotations

import asyncio
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
  "series": [
    {{"date": "ГГГГ-ММ-ДД", "laboratory": "лаборатория из этой строки таблицы или null", "values": {{"ключ": числовое_значение}}, "units": {{"ключ": "единица, только если в этой строке она не та, что в общем units"}}}},
    ...
  ],
  "allergies": ["строка", ...],
  "conditions": ["строка", ...]
}}

Правила:
- "date" — дата, когда сделано исследование или приём. Бери дату с подписью «Дата взятия материала», «Дата забора», «Дата исследования», «Дата приема», «Дата визита» (в таком порядке приоритета). НИКОГДА не бери «Дата печати», «Дата выдачи», «Дата регистрации», «Дата готовности», «Дата рождения» — на бланках лабораторий они часто стоят рядом с датой взятия и позже её на дни и недели. Если на странице нет даты исследования (например, это продолжение документа) — null. На бланке дата обычно ДД.ММ.ГГГГ — переведи в ГГГГ-ММ-ДД и внимательно проверь год.
- "date_label" — подпись, стоящая рядом с выбранной датой, дословно (например «Дата взятия материала»); null, если date null.
- "doc_kind" — тип документа: "lab_panel" — количественные анализы крови и мочи, биохимия, гормоны, витамины, микроэлементы; "imaging" — УЗИ, МРТ, КТ, рентген, ЭКГ, ЭхоКГ; "smear_pcr" — мазки, цитология, ПЦР, ВПЧ, посевы, флороценоз; "doctor_note" — приём, заключение или выписка врача; "other" — анкеты, направления, преаналитика и всё остальное.
- "doc_type" — короткое название, как назвал бы документ врач: «Общий анализ крови», «УЗИ почек», «ПЦР на ВПЧ», «Заключение дерматолога».
- "summary" — что показал документ, только то, что в нём напечатано: результаты, включая качественные («не обнаружено», «1–2 в п/зр»), и заключение/рекомендации врача, если есть. Без советов и интерпретаций от себя. НЕ пиши от себя оценок «в пределах нормы», «всё в порядке», «повышен» — только то, что напечатано на бланке: значение, референс и пометку лаборатории («+», «↑», «H», «*»), если она есть. Разные рекомендации не сливай в одну фразу — перечисли каждую отдельно, как в документе. Для "lab_panel" с числовыми показателями — null (значения уже в "values"); если на бланке анализа только качественные результаты — перечисли их без оценок.
- Для "smear_pcr" поле "values" ВСЕГДА пустое {{}}: результаты мазков и ПЦР качественные или условные («не обнаружено», «1–2 в п/зр», «> 50000», «7×10⁶») — их пиши в "summary", а не в "values".
- "series" — только для сводной таблицы или выписки «в динамике», где показатели приведены за НЕСКОЛЬКО дат (строки или столбцы с датами). Тогда каждая дата таблицы — отдельный элемент "series" со своими значениями (и лабораторией, если она указана в этой строке), а верхние "date" = null и "values" = {{}}. Дату элемента бери из строки или столбца таблицы; дату без дня («03.2023», «2023») не выдумывай — такую строку пропусти. Прочерк или пустая ячейка — показатель в этой дате не включай. Единицы — в общем "units"; если у строки своя единица (столбец «Ед.», сноска «2022 — нг/мл»), укажи её в "units" этого элемента. Если рядом со значением приведён пересчёт в другую единицу («77.7 нмоль/л (≈31.1 нг/мл)»), бери одно значение и укажи именно его единицу — число и единица должны соответствовать друг другу. Сводная таблица анализов — тоже "lab_panel". У обычного бланка за одну дату "series" = [].
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


async def _call_anthropic(messages: list[dict], effort: Optional[str] = None) -> dict:
    """Вызов Anthropic Messages API. `effort` — `output_config.effort`; None — дефолт модели."""
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY не настроен")

    # 180 с: Sonnet 5 + thinking + до 4096 токенов ответа не укладывается в 60 с на
    # плотной странице, а тайм-аут = потерянный документ (ревью #560).
    # 300 с — под лимит ответа 16000 (#559).
    async with httpx.AsyncClient(timeout=300.0) as client:
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
                # этот лимит). Обрезанный JSON = потерянный документ (#558). Сводная
                # таблица за 10+ дат («series») втрое длиннее обычного бланка (#559);
                # платим за фактически выданные токены, не за лимит. На плотной
                # таблице досье 8192 целиком ушли в thinking — JSON пустой (#559).
                "max_tokens": 16000,
                "system": _SYSTEM_PROMPT,
                "messages": messages,
                **({"output_config": {"effort": effort}} if effort else {}),
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


def _build_text_message(file_bytes: bytes, context: Optional[str] = None) -> dict:
    """Собирает Anthropic-сообщение из уже извлечённого текста документа (text-блок).

    Используется для PDF с текстовым слоем: текст извлекается в вызывающем коде и
    приходит сюда байтами. Раньше такой вход ошибочно паковался в image-блок с
    media_type=text/plain, который Anthropic отклоняет (см. #319)."""
    doc_text = file_bytes.decode("utf-8", errors="replace")
    if context:
        # Часть длинного документа (#559): без шапки страница-продолжение не знает ни
        # даты взятия, ни единиц («мг/дл» в заголовке таблицы), ни названий столбцов.
        return {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Начало документа и конец предыдущей страницы — только для контекста (единицы, "
                    "названия столбцов и показателей). Значения и даты из этого блока не извлекай:\n" + context,
                },
                {"type": "text", "text": doc_text},
                {
                    "type": "text",
                    # Дату — только из фрагмента: в шапке досье бывает «Дата формирования»
                    # или первая строка таблицы за 2016 год, и числа без даты легли бы в
                    # динамику чужим днём (ревью #564). Страница-продолжение бланка за
                    # одну дату получает её при склейке (merge_extractions).
                    "text": "Извлеки медицинские данные из этого фрагмента длинного документа. Дату бери только "
                    "из самого фрагмента; если её там нет — null. Единицы, которых нет во фрагменте, — из начала "
                    "документа.",
                },
            ],
        }
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


def _check_date(raw: Any, label: Any = None, today: Optional[date] = None) -> tuple[Optional[str], Optional[str]]:
    """(ISO-дата, None) или (None, причина отказа): not_iso, print_or_issue_date, future."""
    try:
        parsed = date.fromisoformat(str(raw).strip())
    except ValueError:
        return None, "not_iso"
    if any(marker in str(label or "").casefold() for marker in _NON_STUDY_DATE_LABELS):
        return None, "print_or_issue_date"
    if parsed > (today or date.today()) + timedelta(days=1):
        # +1 день: сервер в UTC, а у пользователя в Москве/Израиле уже «завтра».
        return None, "future"
    return parsed.isoformat(), None


def _sanitize_date(data: dict, today: Optional[date] = None) -> None:
    """Проверяет `date` ответа модели на месте; неподходящую — обнуляет.

    Причина отказа — в `_date_rejected` (для логов и превью): not_iso,
    print_or_issue_date (модель сама подписала дату как печать/выдачу), future.
    Дату не угадываем и не чиним — только отказываемся от явно неверной.
    """
    raw = data.get("date")
    if raw is None:
        return
    iso, reason = _check_date(raw, data.get("date_label"), today)
    if iso is not None:
        data["date"] = iso
        return
    logger.info("doc_extractor: дата %r (подпись %r) отброшена: %s", raw, data.get("date_label"), reason)
    data["date"] = None
    data["_date_rejected"] = reason


# Пустая ячейка сводной таблицы — не значение (модель иногда переносит прочерк).
_EMPTY_CELLS = frozenset({"", "—", "-", "–", "н/д", "нет"})


def _series_values(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): v for k, v in raw.items() if v is not None and not (isinstance(v, str) and v.strip() in _EMPTY_CELLS)
    }


def _normalize_series(data: dict, today: Optional[date] = None) -> None:
    """Сводная таблица за несколько дат → `series` по одной записи на дату (#559).

    Элемент без ISO-даты или с будущей датой отбрасывается (дату не угадываем —
    «03.2023» не становится 1 марта), причины — в `_series_rejected`. Записи за
    одну дату склеиваются (совпавший ключ — первое значение). Вышла одна дата —
    это обычный документ: дата и значения поднимаются наверх, `series` убирается,
    и все читатели документа работают как раньше. Две и больше — верхние
    `date`/`values` описывают только то, что даты не имеет.
    """
    raw = data.pop("series", None)
    by_date: dict[str, dict[str, Any]] = {}
    rejected: list[str] = []

    def _add(iso: str, laboratory: Any, values: dict[str, Any], units: Any = None) -> None:
        entry = by_date.setdefault(iso, {"date": iso, "laboratory": None, "values": {}})
        if laboratory and not entry["laboratory"]:
            entry["laboratory"] = str(laboratory).strip() or None
        for key, value in values.items():
            if key in entry["values"]:
                continue
            entry["values"][key] = value
            # Своя единица строки (#559): в досье витамин D одной даты — нмоль/л,
            # остальных — нг/мл. Хранится только для ключей этой записи.
            if isinstance(units, dict) and units.get(key):
                entry.setdefault("units", {})[key] = str(units[key])

    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        values = _series_values(item.get("values"))
        if not values:
            continue
        iso, reason = _check_date(item.get("date"), None, today)
        if iso is None:
            rejected.append(f"{item.get('date')!r}: {reason}")
            continue
        _add(iso, item.get("laboratory"), values, item.get("units"))
    if rejected:
        logger.info("doc_extractor: строки сводной таблицы отброшены: %s", rejected)
        data["_series_rejected"] = rejected
    if not by_date:
        return

    top_values = data.get("values") if isinstance(data.get("values"), dict) else {}
    if data.get("date") and top_values:
        _add(data["date"], data.get("laboratory"), top_values)
        top_values = {}
    if len(by_date) == 1:
        (entry,) = by_date.values()
        data["date"] = entry["date"]
        data["values"] = {**top_values, **entry["values"]}
        data["laboratory"] = data.get("laboratory") or entry["laboratory"]
        if entry.get("units"):
            data["units"] = {**(data.get("units") if isinstance(data.get("units"), dict) else {}), **entry["units"]}
        return
    data["date"] = None
    data["values"] = top_values
    data["series"] = [by_date[d] for d in sorted(by_date)]


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
    if data.get("doc_kind") == "lab_panel" and data.get("summary") and (data.get("values") or data.get("series")):
        # Резюме анализов от модели не храним: она регулярно пишет «все показатели в
        # пределах нормы» при значениях выше нормы (кальций 1.33 при норме до 1.32,
        # RBC 6.18 при норме до 5.70), и никакой фильтр фраз её не догоняет — каждая
        # новая формулировка проходит. Значения лежат рядом, оценка — дело агента по
        # референсам. Бланк анализа без чисел (серология, «не обнаружено») резюме
        # сохраняет — это пересказ напечатанного. У УЗИ/мазков/заключений тоже (#558).
        data["summary"] = None
    values = data.get("values")
    if data.get("doc_kind") == "smear_pcr" and isinstance(values, dict) and values:
        logger.info("doc_extractor: у smear_pcr отброшены числа: %s", list(values))
        data["_dropped_values"] = values
        data["values"] = {}
    if data.get("doc_kind") == "smear_pcr" and data.get("series"):
        logger.info("doc_extractor: у smear_pcr отброшена сводная таблица (%d дат)", len(data["series"]))
        data["_dropped_series"] = data.pop("series")


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
# Досье #559: 25-OH витамин D в нмоль/л (1 нг/мл = 2.496 нмоль/л), общий тестостерон
# в нг/мл (1 нг/мл = 3.467 нмоль/л) — строки одной таблицы в разных единицах.
_UNIT_CONVERSIONS.update(
    {
        (key, unit): (round(1 / 2.496, 6), "нг/мл")
        for key in ("vitamin_d", "vitamin_d3", "vitd", "vit_d")
        for unit in ("нмоль/л", "nmol/l")
    }
)
_UNIT_CONVERSIONS.update(
    {
        (key, unit): (3.467, "нмоль/л")
        for key in ("testosterone", "testosterone_total", "total_testosterone")
        for unit in ("нг/мл", "ng/ml")
    }
)


def _convert_units(data: dict) -> None:
    """Пересчитывает значения, напечатанные не в канонической единице (СРБ в мг/дл).

    Сделанные пересчёты — в `_unit_conversions`; единица пересчитанного ключа
    обновляется на каноническую, чтобы повторная обработка не умножила ещё раз.
    У сводной таблицы (#559) единица значения — своя у строки (`series[].units`),
    иначе общая `units`; общие единицы берутся в исходном виде для всех дат.
    """
    top_units = data.get("units") if isinstance(data.get("units"), dict) else {}
    original = dict(top_units)
    done: list[str] = []
    top_converted: dict[str, str] = {}

    def _apply(values: Any, units: dict, where: str) -> dict[str, str]:
        changed: dict[str, str] = {}
        if not isinstance(values, dict):
            return changed
        for key, raw in list(values.items()):
            unit = units.get(key)
            if unit is None or not isinstance(raw, (int, float)) or isinstance(raw, bool):
                continue
            rule = _UNIT_CONVERSIONS.get((str(key).casefold(), "".join(str(unit).split()).casefold()))
            if rule is None:
                continue
            factor, canon_unit = rule
            values[key] = round(raw * factor, 6)
            changed[key] = canon_unit
            done.append(f"{where}{key}: {unit} → {canon_unit} ×{factor:g}")
        return changed

    top_converted.update(_apply(data.get("values"), original, ""))
    for entry in data.get("series") or []:
        if not isinstance(entry, dict):
            continue
        own = entry.get("units") if isinstance(entry.get("units"), dict) else {}
        for key, canon_unit in _apply(entry.get("values"), {**original, **own}, f"{entry.get('date')} ").items():
            if key in own:
                own[key] = canon_unit
            else:
                top_converted[key] = canon_unit
    if top_converted and isinstance(data.get("units"), dict):
        data["units"].update(top_converted)
    if done:
        logger.info("doc_extractor: пересчёт единиц: %s", done)
        data["_unit_conversions"] = done


def _as_str_list(v) -> list[str]:
    """Безопасно привести значение к списку непустых строк. Не-список → []."""
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


async def extract_medical_data(
    file_bytes: bytes,
    mime_type: str,
    user_id: Optional[int] = None,
    *,
    context: Optional[str] = None,
    check_readable: bool = True,
    effort: Optional[str] = None,
) -> dict[str, Any]:
    """Извлекает медицинские данные из документа через Claude.

    Args:
        file_bytes: байты файла (PDF или изображение)
        mime_type: MIME-тип файла
        user_id: владелец документа — для учёта расходов в llm_usage_log
        context: начало документа для части длинного PDF (#559), только text/plain
        check_readable: False — читаемость уже проверена на всём документе (#559):
            страница таблицы из дат и чисел сама по себе «без букв», но не мусор
        effort: `output_config.effort` (low…max); None — дефолт модели (high у Sonnet 5)

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
        if mime_type == "text/plain" and check_readable:
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
            message = _build_text_message(file_bytes, context)
        else:
            message = _build_image_message(file_bytes, mime_type)

        response = await _call_anthropic([message], effort) if effort else await _call_anthropic([message])
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
            _normalize_series(data)
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


# Длинный текстовый PDF одним вызовом не помещается в ответ: 15-страничное досье
# (36 тыс. символов) обрывалось по max_tokens даже на 4096 (#559). Режем по страницам
# на части не длиннее _CHUNK_CHARS и разбираем параллельно. Части по 8 тыс. символов
# на том же досье обрывались 3 из 5 — модель тратила весь лимит на thinking над
# плотной таблицей, поэтому часть ≈ одна страница. Обычный бланк (у всех
# пользователей на 26.09.2026 — до 4.2 тыс. символов) идёт одним вызовом, как раньше:
# при разрезе страница-продолжение теряла бы дату первой страницы.
_CHUNK_THRESHOLD_CHARS = 12_000
_CHUNK_CHARS = 3_500
# 15-страничное досье: 3 параллельно — 363 с (пять кругов по ~70 с thinking на
# часть), 6 — три круга. Больше — упираемся в лимит запросов Anthropic.
_MAX_PARALLEL_CHUNKS = 6
# Начало первой страницы и конец предыдущей части — контекст каждой следующей части:
# единицы и названия столбцов (ревью #564). Дату из него модель не берёт — см.
# _build_text_message.
_CONTEXT_CHARS = 1_500
# Thinking на плотной странице таблицы при дефолтном high иногда съедает весь лимит
# 16000 дважды подряд (досье #559). effort — рекомендованный Anthropic регулятор
# глубины thinking у Sonnet 5 (docs: build-with-claude/effort). Только для частей
# длинного документа: обычные бланки мерены eval'ом на дефолте (ADR-0010).
_CHUNK_EFFORT = "medium"


def needs_chunking(pages: list[str]) -> bool:
    """Длинный документ — разбор по частям, дольше обычного (показать пользователю)."""
    return len("\n".join(pages)) > _CHUNK_THRESHOLD_CHARS


def chunk_pages(pages: list[str], limit: int = _CHUNK_CHARS) -> list[str]:
    """Страницы → части не длиннее `limit` символов; страница не режется."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for page in pages:
        if current and size + len(page) > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(page)
        size += len(page)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def merge_extractions(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Склеивает разборы частей одного документа в один `extracted` (#559).

    Даты и значения всех частей собираются в `series` и проходят ту же
    нормализацию, что и ответ одного вызова: одна дата на весь документ — обычный
    документ, несколько — сводная таблица. Значения части без даты остаются
    наверху: при одной дате документа они к ней и относятся (страница-продолжение),
    при нескольких — в динамику не идут.
    """
    parts = [p for p in parts if p]
    if not parts:
        return {}
    series: list[dict[str, Any]] = []
    undated: dict[str, Any] = {}
    units: dict[str, Any] = {}
    fallback_units: dict[str, Any] = {}

    def _entry_units(part_units: dict, entry_values: dict, own: Any) -> dict:
        # Единица каждой даты — итоговая единица её части: общие units склеенного
        # документа берутся из первой части, и единица другой части иначе пропала бы
        # (пролактин мкМЕ/мл одной части среди нг/мл другой — ревью #564).
        own = own if isinstance(own, dict) else {}
        return {k: own.get(k) or part_units[k] for k in entry_values if own.get(k) or part_units.get(k)}

    for part in parts:
        part_units = part.get("units") if isinstance(part.get("units"), dict) else {}
        for entry in part.get("series") or []:
            if isinstance(entry, dict):
                entry_values = entry.get("values") if isinstance(entry.get("values"), dict) else {}
                series.append(
                    {
                        **entry,
                        "laboratory": entry.get("laboratory") or part.get("laboratory"),
                        "units": _entry_units(part_units, entry_values, entry.get("units")),
                    }
                )
        values = part.get("values") if isinstance(part.get("values"), dict) else {}
        if part.get("date") and values:
            series.append(
                {
                    "date": part["date"],
                    "laboratory": part.get("laboratory"),
                    "values": values,
                    "units": _entry_units(part_units, values, None),
                }
            )
        else:
            for key, value in values.items():
                undated.setdefault(key, value)
        if isinstance(part.get("units"), dict):
            # Единица ключа — из части, где этот ключ есть: у части без значений
            # единица не пересчитана и осталась бы бланковой (ревью #564).
            present = set(values) | {k for e in part.get("series") or [] for k in (e.get("values") or {})}
            for key, unit in part["units"].items():
                if key in present:
                    units.setdefault(key, unit)
                else:
                    fallback_units.setdefault(key, unit)

    rejected = [r for p in parts for r in p.get("_series_rejected") or []]
    rejected += [f"{p.get('_date_rejected')}: дата части" for p in parts if p.get("_date_rejected")]
    kinds = [p.get("doc_kind") for p in parts if p.get("doc_kind")]
    merged: dict[str, Any] = {
        "date": None,
        "laboratory": next((p["laboratory"] for p in parts if p.get("laboratory")), None),
        "doc_type": next((p["doc_type"] for p in parts if p.get("doc_type")), None),
        "summary": "\n".join(_unique([p["summary"] for p in parts if p.get("summary")])) or None,
        "values": undated,
        "units": {**fallback_units, **units},
        "series": series,
        "allergies": _unique([a for p in parts for a in p.get("allergies") or []]),
        "conditions": _unique([c for p in parts for c in p.get("conditions") or []]),
        "_chunks": len(parts),
    }
    if kinds:
        merged["doc_kind"] = "lab_panel" if "lab_panel" in kinds else kinds[0]
    _normalize_series(merged)
    _normalize_kind(merged)
    if rejected:
        merged["_series_rejected"] = rejected + merged.get("_series_rejected", [])
    return merged


async def extract_medical_data_from_pages(pages: list[str], user_id: Optional[int] = None) -> dict[str, Any]:
    """Текстовый PDF постранично: короткий — одним вызовом, длинный — по частям (#559)."""
    text = "\n".join(pages)
    # Читаемость — по всему документу (#509): отдельная страница таблицы из дат и
    # чисел гейт не проходит, хотя документ целиком читается (ревью #564).
    if not needs_chunking(pages) or not is_document_text_readable(text):
        return await extract_medical_data(text.encode(), "text/plain", user_id=user_id)
    chunks = chunk_pages(pages)
    head = pages[0][:_CONTEXT_CHARS]

    def _context(i: int) -> Optional[str]:
        # Шапка документа + конец предыдущей части: заголовок таблицы часто стоит в
        # конце страницы, а её строки — на следующей (досье #559: гормоны — названия
        # столбцов на стр. 4, числа на стр. 5; без них модель либо пропускала числа,
        # либо угадывала названия).
        if i == 0:
            return None
        tail = chunks[i - 1][-_CONTEXT_CHARS:]
        if "\n" in tail:
            # По границе строки: обрубок «1.03.2023» вместо «11.03.2023» — другая дата.
            tail = tail.split("\n", 1)[1]
        return tail if i == 1 and len(chunks[0]) <= _CONTEXT_CHARS else f"{head}\n…\n{tail}"

    logger.info("doc_extractor: длинный документ (%d символов) — разбор по %d частям", len(text), len(chunks))
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_CHUNKS)

    async def _one(i: int, chunk: str) -> dict[str, Any]:
        async with semaphore:
            return await extract_medical_data(
                chunk.encode(),
                "text/plain",
                user_id=user_id,
                context=_context(i),
                check_readable=False,
                effort=_CHUNK_EFFORT,
            )

    parts = list(await asyncio.gather(*(_one(i, c) for i, c in enumerate(chunks))))
    # Один повтор неразобранных частей: обрыв по max_tokens — это thinking, ушедший
    # в разнос на плотной таблице, и повторный вызов обычно укладывается (прогон
    # досье #559: 1 из 15 частей). Платим за повтор только при сбое.
    retry = [i for i, p in enumerate(parts) if not p]
    if retry:
        logger.info("doc_extractor: повтор %d неразобранных частей", len(retry))
        again = await asyncio.gather(*(_one(i, chunks[i]) for i in retry))
        for i, part in zip(retry, again):
            parts[i] = part
    failed = sum(1 for p in parts if not p)
    if failed:
        logger.warning("doc_extractor: %d из %d частей не разобрались", failed, len(parts))
    merged = merge_extractions(parts)
    if merged:
        merged["_chunks_total"] = len(chunks)
        if failed:
            merged["_chunks_failed"] = failed
    return merged
