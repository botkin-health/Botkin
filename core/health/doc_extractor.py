# core/health/doc_extractor.py
"""Извлечение медицинских данных из документов через Anthropic Claude."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

import httpx

from config.models import DOC_EXTRACT_MODEL
from config.settings import get_settings
from core.health.doc_marker_labels import split_verified_values
from core.health.doc_normalize import LAB_PANEL, normalize_extracted
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
            normalize_extracted(data)
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
        merged["doc_kind"] = LAB_PANEL if LAB_PANEL in kinds else kinds[0]
    normalize_extracted(merged)
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
