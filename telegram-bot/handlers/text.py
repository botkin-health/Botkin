#!/usr/bin/env python3
"""
Обработчик текстовых сообщений и голосовых сообщений
"""

import re
import asyncio
from datetime import datetime, timedelta, timezone

# Московское время (UTC+3)
MSK = timezone(timedelta(hours=3))

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from services.state import state_manager

router = Router()


_QUESTION_STARTERS = (
    "как",
    "что",
    "почему",
    "зачем",
    "когда",
    "сколько",
    "какой",
    "какая",
    "какие",
    "какое",
    "где",
    "куда",
    "откуда",
    "напомни",
    "посчитай",
    "покажи",
    "расскажи",
    "объясни",
    "подскажи",
    "сравни",
    "оцени",
    "может",
    "можно",
    "нужно",
    "стоит ли",
)
# Word-boundary regex — avoids matching 'дела' as containing 'ела'.
_FOOD_DISQUALIFIER_RE = re.compile(
    r"\b("
    r"съел|съела|ел|ела|выпил|выпила|пью|выпью|"
    r"позавтракал|пообедал|поужинал|перекусил|перекусила|"
    r"граммов?|ккал|калори|белков?|жиров?|углеводов?|клетчатк|"
    r"завтрак|обед|ужин|перекус|бранч|полдник"
    r")\b",
    re.IGNORECASE,
)
# Numeric weight/dose: "200г", "120/80", "5000 МЕ", "5 шт"
_NUMERIC_DOSE_RE = re.compile(
    r"\d+\s*(?:г|мг|мл|кг|/|ме|iu|шт|капсул|таблеток)",
    re.IGNORECASE,
)


def _is_clearly_conversational(text: str) -> bool:
    """Cheap heuristic: looks like a question, NOT a food/log entry.

    Used to skip the Sonnet-4.5 LLM router for obvious conversational
    text — saves ~$0.04 per message (see admin /api/llm_usage panel).
    Conservative: false negatives (food sent to agent) are harmless because
    the agent declines to log without explicit user intent.
    """
    if not text:
        return False
    t = text.strip()

    if _FOOD_DISQUALIFIER_RE.search(t):
        return False
    if _NUMERIC_DOSE_RE.search(t):
        return False

    # Strong signal: explicit question
    if "?" in t:
        return True

    # Starts with a question word
    first_word = t.lower().split(maxsplit=1)[0] if t else ""
    if any(first_word == qw for qw in _QUESTION_STARTERS):
        return True

    return False


def _is_food_description(text: str) -> bool:
    """
    Определяет, является ли текст описанием еды.

    Args:
        text: Текст сообщения

    Returns:
        True, если это описание еды
    """
    if not text:
        return False

    text_lower = text.lower().strip()

    # Индикаторы еды (сильные)
    strong_food_indicators = [
        # Единицы измерения еды
        r"\d+\s*(г|грамм|граммов|кг|килограмм)",
        r"\d+\s*(мл|миллилитр|л|литр)",
        r"\d+\s*(ч\.?\s*л\.?|чайн\w*\s*лож\w*|столов\w*\s*лож\w*)",
        r"\d+\s*(стакан|чашк|тарелк|порци)",
        r"\d+\s*(штук|шт\.?|кусоч|ломтик)",
        # Описание времени приема пищи
        r"(завтрак|обед|ужин|перекус|бранч|полдник)\s*[:\-]",
        r"(на\s+)?(завтрак|обед|ужин|перекус)",
        r"(утром|днем|вечером|ночью)\s*(ел|съел|поел)",
        # Указания на прием пищи во времени
        r"(вчера|сегодня|позавчера)\s+(завтрак|обед|ужин|перекус|ел|съел)",
        r"(завтрак|обед|ужин|перекус)\s+(вчера|сегодня)",
        # Процессы приготовления
        r"(варен\w*|жарен\w*|тушен\w*|печен\w*|сыр\w*)",
        r"(приготовил|готовил|сделал|смешал)\s",
    ]

    # Продукты питания (средние индикаторы)
    food_keywords = [
        "яйц",
        "курин",
        "мяс",
        "рыб",
        "сыр",
        "молок",
        "творог",
        "йогурт",
        "хлеб",
        "каш",
        "рис",
        "греч",
        "овся",
        "макарон",
        "спагетти",
        "картофел",
        "овощ",
        "помидор",
        "огурец",
        "лук",
        "морков",
        "капуст",
        "яблок",
        "банан",
        "апельсин",
        "фрукт",
        "ягод",
        "масл",
        "соус",
        "солен",
        "сахар",
        "мед",
        "печень",
        "орех",
        "семеч",
        "крупа",
        "бобов",
    ]

    # Проверяем сильные индикаторы
    for pattern in strong_food_indicators:
        if re.search(pattern, text_lower):
            return True

    # Если есть продукты И это достаточно длинное описание
    food_keyword_count = sum(1 for keyword in food_keywords if keyword in text_lower)
    if food_keyword_count >= 1 and len(text) > 15:
        return True

    # Специальная проверка для сообщений с весом/количеством
    if re.search(r"\d+.*(?:г|грамм|мл|ложк|стакан|штук|кусоч|порци)", text_lower) and len(text) > 10:
        return True

    return False


_SLOT_PREFIX_MAP = {
    "завтрак": "Завтрак",
    "обед": "Обед",
    "ужин": "Ужин",
    "перекус": "Перекус",
    "бранч": "Бранч",
    "полдник": "Полдник",
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "dinner": "Ужин",
    "snack": "Перекус",
    "brunch": "Бранч",
}


def detect_slot_prefix(text: str) -> str | None:
    """Вернуть 'Завтрак'/'Обед'/... если текст начинается со слова-слота, иначе None.

    Распознаются:
      - голое слово: "Завтрак", "Обед"
      - слово + разделитель: "Завтрак: овсянка", "Обед - суп", "Ужин — рыба"
      - слово + описание: "Завтрак с кофе", "Обед в ресторане"
      - эмодзи/символ перед словом: "🌅 Завтрак", "🍽 Обед"
      - английские варианты: "breakfast", "lunch", "dinner", "snack", "brunch"

    НЕ распознаются (чтобы не перекрывать time-based slotting):
      - глагольные формы: "завтракаю", "обедаю"
      - квалификаторы: "Поздний обед", "поздний завтрак"
      - предлоги: "на завтрак ем..."
    """
    if not text or not text.strip():
        return None
    # Убираем ведущие не-словесные символы (эмодзи, пробелы, пунктуацию) —
    # аналогично webhook.nutrition_slots._starts_with_token для консистентности.
    stripped = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE)
    m = re.match(
        r"^(завтрак|обед|ужин|перекус|бранч|полдник|breakfast|lunch|dinner|snack|brunch)\b",
        stripped,
        re.IGNORECASE,
    )
    if not m:
        return None
    return _SLOT_PREFIX_MAP.get(m.group(1).lower())


def apply_slot_prefix(text: str, meal_name: str | None) -> str | None:
    """Если у пользовательского текста есть префикс слота, приклеить его к meal_name."""
    if not meal_name:
        return meal_name
    prefix = detect_slot_prefix(text)
    if prefix and not meal_name.lower().startswith(prefix.lower()):
        return f"{prefix}: {meal_name}"
    return meal_name


def extract_meal_name(text: str, meal_time: str = None) -> str:
    """
    Извлекает название приёма пищи из текста.
    Если не найдено в тексте, определяет по времени суток.

    Args:
        text: Текст описания
        meal_time: Время приёма пищи в формате "HH:MM" (опционально)

    Returns:
        Название приёма пищи: "Завтрак", "Обед", "Ужин" и т.д.
    """
    text_lower = text.lower()

    # Паттерны для поиска названия приёма пищи
    meal_patterns = [
        (
            r"^(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)\s*[:]",
            "ru",
        ),  # "обед: яичница..."
        (r"как\s+(?:мой|мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)", "ru"),
        (
            r"это\s+(?:мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)",
            "ru",
        ),  # "да, это завтрак"
        (r"(?:мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)", "ru"),
        (r"^(breakfast|lunch|dinner|snack|brunch)\s*[:]", "en"),  # "lunch: ..."
        (r"for\s+(?:my\s+)?(breakfast|lunch|dinner|snack|brunch)", "en"),  # "for dinner I mixed..."
        (r"(?:as\s+)?(?:my\s+)?(breakfast|lunch|dinner|snack|brunch)", "en"),
    ]

    for pattern, lang in meal_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            meal_name = match.group(1)
            # Капитализуем первую букву
            if lang == "ru":
                # Русские названия
                meal_map = {
                    "завтрак": "Завтрак",
                    "обед": "Обед",
                    "ужин": "Ужин",
                    "перекус": "Перекус",
                    "бранч": "Бранч",
                    "полдник": "Полдник",
                    "ранний ужин": "Ранний ужин",
                    "вечерний перекус": "Вечерний перекус",
                }
                return meal_map.get(meal_name, meal_name.capitalize())
            else:
                # Английские названия
                meal_map = {
                    "breakfast": "Завтрак",
                    "lunch": "Обед",
                    "dinner": "Ужин",
                    "snack": "Перекус",
                    "brunch": "Бранч",
                }
                return meal_map.get(meal_name.lower(), meal_name.capitalize())

    # Если не найдено в тексте, определяем по времени суток
    if meal_time:
        try:
            hour = int(meal_time.split(":")[0])
            if 5 <= hour < 11:
                return "Завтрак"
            elif 11 <= hour < 15:
                return "Обед"
            elif 15 <= hour < 18:
                return "Полдник"
            elif 18 <= hour < 22:
                return "Ужин"
            else:
                return "Вечерний перекус"
        except (ValueError, IndexError):
            pass

    # Если время не указано, используем текущее время (Москва)
    current_hour = datetime.now(MSK).hour
    if 5 <= current_hour < 11:
        return "Завтрак"
    elif 11 <= current_hour < 15:
        return "Обед"
    elif 15 <= current_hour < 18:
        return "Полдник"
    elif 18 <= current_hour < 22:
        return "Ужин"
    else:
        return "Вечерний перекус"


def extract_date_from_text(text: str) -> tuple[str, str]:
    """
    Извлекает дату "вчера" из начала текста.
    Возвращает (date_str, clean_text).
    date_str в формате YYYY-MM-DD или None (если сегодня).
    """
    if not text:
        return None, text

    text_lower = text.lower().strip()

    # Ключевые слова для "вчера" / "позавчера"
    relative_keywords = [
        ("позавчера", 2),
        ("day before yesterday", 2),
        ("вчера", 1),
        ("yesterday", 1),
    ]

    # Проверяем начало строки
    # Например: "Вчера ужин: ..." или "Позавчера: ..."
    # 1. Проверка "вчера" / "позавчера" / "yesterday"
    for kw, days_ago in relative_keywords:
        if text_lower.startswith(kw):
            # Проверяем, что идет после ключевого слова
            after_kw = text_lower[len(kw) :]

            target_date = datetime.now(MSK) - timedelta(days=days_ago)
            date_str = target_date.strftime("%Y-%m-%d")

            # Если текст закончился - это просто "вчера" / "позавчера"
            if not after_kw:
                return date_str, ""

            # Если после ключевого слова идет разделитель
            if after_kw[0] in [":", ",", "-", " ", "\n"]:
                clean_text = text[len(kw) :].strip()
                clean_text = re.sub(r"^[:,\-\s]+", "", clean_text).strip()
                return date_str, clean_text

    # 2. Проверка даты в формате ДД.ММ или ДД/ММ (например "29.01", "29/01")
    # Ищем в начале строки
    date_match = re.match(r"^(\d{1,2})[./](\d{1,2})\s*", text_lower)
    if date_match:
        day, month = int(date_match.group(1)), int(date_match.group(2))
        try:
            # Предполагаем текущий год. Если месяц больше текущего - значит прошлый год?
            # Нет, просто текущий год для простоты, или умная логика
            current_year = datetime.now(MSK).year
            # Если дата в будущем (например, сегодня 01.02, а ввели 29.01) - это ок
            target_date = datetime(current_year, month, day, tzinfo=MSK)
            if target_date > datetime.now(MSK) + timedelta(days=1):
                target_date = datetime(current_year - 1, month, day, tzinfo=MSK)

            date_str = target_date.strftime("%Y-%m-%d")
            clean_text = text[date_match.end() :].strip()
            # Убираем разделители, если остались
            clean_text = re.sub(r"^[:,\-\s]+", "", clean_text).strip()
            return date_str, clean_text
        except ValueError:
            pass  # Invalid date

    # 3. Проверка даты текстом (например "29 января", "29-го января")
    months = {
        "январ": 1,
        "феврал": 2,
        "март": 3,
        "апрел": 4,
        "мая": 5,
        "май": 5,
        "июн": 6,
        "июл": 7,
        "август": 8,
        "сентябр": 9,
        "октябр": 10,
        "ноябр": 11,
        "декабр": 12,
    }

    # Регулярка для "29-го января", "29-е апреля", "29 января", "ужин 19-е апреля:"
    # Ищем где угодно в тексте (не только в начале), суффиксы -го/-е/-ого и без
    text_date_match = re.search(r"(\d{1,2})(?:-?(?:го|е|ого))?\s+([а-я]+)", text_lower)
    if text_date_match:
        day = int(text_date_match.group(1))
        month_str = text_date_match.group(2)

        # Ищем месяц
        month = 0
        for m_name, m_num in months.items():
            if month_str.startswith(m_name):
                month = m_num
                break

        if month > 0:
            try:
                current_year = datetime.now(MSK).year
                target_date = datetime(current_year, month, day, tzinfo=MSK)
                if target_date > datetime.now(MSK) + timedelta(days=1):
                    target_date = datetime(current_year - 1, month, day, tzinfo=MSK)

                date_str = target_date.strftime("%Y-%m-%d")
                # Убираем всё до конца даты (включая само упоминание даты)
                clean_text = text[text_date_match.end() :].strip()
                clean_text = re.sub(r"^[:,\-\s]+", "", clean_text).strip()
                # Если перед датой было слово (например "ужин") — добавляем его обратно
                prefix = text[: text_date_match.start()].strip()
                if prefix:
                    prefix = re.sub(r"[:,\-\s]+$", "", prefix).strip()
                    clean_text = f"{prefix} {clean_text}".strip() if prefix else clean_text
                return date_str, clean_text
            except ValueError:
                pass

    return None, text


def is_confirmation(text: str) -> bool:
    """
    Проверяет, является ли текст подтверждением сохранения.
    """
    text_lower = text.lower().strip()

    # Паттерны подтверждения
    confirm_patterns = [
        r"^(да|yes|сохрани|save|ок|ok|хорошо|сохранить)",
        r"^(да|yes).*сохрани",
        r"сохрани.*(да|yes)",
    ]

    for pattern in confirm_patterns:
        if re.match(pattern, text_lower):
            return True

    return False


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message, user_id: int, state: FSMContext):
    """Обработчик текстовых сообщений (БЕЗ фото)"""
    import logging

    logger = logging.getLogger(__name__)

    # Не обрабатываем команды (они обрабатываются в handlers/commands.py)
    if message.text and message.text.startswith("/"):
        logger.debug(f"Пропущена команда: {message.text}")
        return

    # Дополнительная проверка на случай, если фильтр не сработал
    if message.photo:
        logger.warning("⚠️ Обработчик текста получил сообщение с фото - пропускаем")
        return

    user_id = str(message.from_user.id)
    user_state = state_manager.get_state(user_id)

    # Логируем ВСЕ текстовые сообщения для отладки
    text_preview = message.text[:100] if message.text else "None"
    logger.info(f"📝 Обработчик текста: получено сообщение от {user_id}: '{text_preview}...'")

    if user_state:
        logger.info(f"Состояние пользователя {user_id}: {user_state.state}")
        logger.info(f"Данные состояния: {list(user_state.data.keys())}")
    else:
        logger.info(f"У пользователя {user_id} нет состояния")

    # Проверяем, ожидается ли описание (после фото)
    if user_state and user_state.state == "waiting_description":
        # Обрабатываем как описание блюда
        from handlers.photo import handle_description

        await handle_description(message, message.text)
        return

    # --- LLM Router Logic ---
    from core.llm.router import analyze_message
    from core.food.nutrition import process_llm_food_data
    import html
    import logging

    # Configure specific logger for debugging
    debug_logger = logging.getLogger("bot_debug")
    debug_logger.setLevel(logging.DEBUG)

    # Check if handler already exists to avoid duplicates
    if not debug_logger.handlers:
        fh = logging.FileHandler("logs/bot_debug.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        debug_logger.addHandler(fh)

    text = message.text.strip()
    debug_logger.info(f"🚀 START Processing message from {user_id}: {text[:50]}...")

    # Индикатор "печатает..." крутится через TypingMiddleware.
    # Плейсхолдер-сообщение больше не шлём — вместо edit_text шлём новые
    # сообщения через shim, чтобы не переписывать все 15+ call-сайтов.
    class _Replier:
        def __init__(self, msg):
            self._msg = msg

        async def edit_text(self, *args, **kwargs):
            return await self._msg.answer(*args, **kwargs)

    processing_msg = _Replier(message)
    debug_logger.info("✅ Replier shim ready (typing indicator via middleware)")

    # Извлекаем дату "Вчера / 23 мая / 29.01" — нужно для food-логирования
    # ("Вчера ужин: ..."), но НЕ для conversational вопросов
    # ("Как мои анализы от 23 мая?" → "23 мая" вырезалось и Claude получал
    # обрезанное "Как мои анализы от ?", переспрашивал дату).
    # Прецедент 25.05.2026.
    from handlers.text import extract_date_from_text

    custom_date = None
    if not _is_clearly_conversational(text):
        custom_date, clean_text = extract_date_from_text(text)
        if custom_date:
            text = clean_text

    # /my_products feature removed — no early-exit product matching, LLM handles all.
    router_result = None

    # ── BP regex pre-check ──────────────────────────────────────────────────
    # Детерминированный паттерн «XXX/YY пульс ZZ» — мимо LLM-роутера.
    # Прецедент 25.05.2026: папа Александра написал «Сейчас 15:07 151/92 пуль 65»,
    # бот ответил «не удалось понять, что это за еда» (4 раза подряд).
    # LLM-роутер не классифицировал замер АД как `bp`, поэтому ловим regex'ом.
    # Систолика 70-250, диастолика 40-150 — реалистичные границы.
    _BP_RE = re.compile(
        r"(?<![\d.,])(\d{2,3})\s*[/\\]\s*(\d{2,3})"  # XXX/YY (систола/диастола)
        r"(?:[^\d\n]{0,30}?(?:пул[ьсаеыйя]+|чсс|hr|hrm|pulse)[^\d\n]{0,10}?(\d{2,3}))?",
        re.IGNORECASE,
    )
    _TIME_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")

    bp_match = _BP_RE.search(text)
    if bp_match:
        sys_v = int(bp_match.group(1))
        dia_v = int(bp_match.group(2))
        pulse_v = int(bp_match.group(3)) if bp_match.group(3) else None
        # Валидация: реалистичные границы. Иначе это не АД (может, размер обуви
        # «42/12» или что-то ещё). Систолика >= диастолики обязательно.
        if (70 <= sys_v <= 250) and (40 <= dia_v <= 150) and (sys_v > dia_v):
            # Опциональное время «15:07» в тексте — привязываем к сегодня
            measured_at = None
            time_match = _TIME_RE.search(text)
            if time_match:
                hh, mm = int(time_match.group(1)), int(time_match.group(2))
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    from datetime import datetime as _dt

                    # ВАЖНО: используем модульный MSK (объявлен в line 11).
                    # НЕ объявлять MSK здесь локально — иначе Python сделает её
                    # local для ВСЕЙ функции, и в food-flow ниже UnboundLocalError.
                    # Прецедент 25.05.2026: Александр тестировал hot-fix, упало
                    # на "Овсянка 150г" с этим же error'ом.
                    measured_at = _dt.now(MSK).replace(hour=hh, minute=mm, second=0, microsecond=0)

            if pulse_v is not None and not (30 <= pulse_v <= 220):
                pulse_v = None  # неправдоподобный пульс — отбрасываем но BP сохраняем

            from helpers.db_save import save_bp_to_db

            saved = save_bp_to_db(
                systolic=sys_v,
                diastolic=dia_v,
                pulse=pulse_v,
                user_id=int(user_id),
                measured_at=measured_at,
                source="manual_text",
            )
            if saved:
                pulse_part = f" пульс {pulse_v}" if pulse_v else ""
                time_part = f" в {measured_at.strftime('%H:%M')}" if measured_at else ""
                await processing_msg.edit_text(
                    f"🩺 <b>АД:</b> {sys_v}/{dia_v}{pulse_part}{time_part}\n✅ Записано",
                    parse_mode="HTML",
                )
                debug_logger.info(f"✅ BP regex pre-check matched: {sys_v}/{dia_v} pulse={pulse_v}")
                return
            else:
                await processing_msg.edit_text(
                    f"🩺 Распознал давление {sys_v}/{dia_v}, но сохранение в БД не удалось. "
                    f"Попробуй ещё раз через минуту."
                )
                return

    if not router_result:
        # Предварительная проверка экей витаминов ДО вызова LLM — если все слова входят в словарь, не зовём LLM
        _SUPPLEMENT_KEYWORDS = {
            "стирол": "Plant Sterols",
            "стиролы": "Plant Sterols",
            "стирола": "Plant Sterols",
            "стерол": "Plant Sterols",
            "стеролы": "Plant Sterols",
            "стерола": "Plant Sterols",
            "растительные стеролы": "Plant Sterols",
            "растительные стиролы": "Plant Sterols",
            "plant sterols": "Plant Sterols",
            "plant sterol": "Plant Sterols",
            "sterols": "Plant Sterols",
            "sterol": "Plant Sterols",
            "омега": "Омега 3",
            "омегу": "Омега 3",
            "omega": "Омега 3",
            "омега-3": "Омега 3",
            "омега 3-6-9": "Омега 3",
            "ѓ3": "Витамин D3",
            "витамин д": "Витамин D3",
            "витамин d": "Витамин D3",
            "d3": "Витамин D3",
            "псиллиум": "Псиллиум",
            "псилиум": "Псиллиум",
            "psyllium": "Псиллиум",
            "магний": "Магний",
            "магне": "Магний",
            "magnesium": "Магний",
            "цинк": "Цинк",
            "zinc": "Цинк",
            "креатин": "Креатин",
            "creatine": "Креатин",
            "kreatin": "Креатин",
            "кретин": "Креатин",
            "моногидрат": "Креатин",
            "метилфолат": "Метилфолат",
            "метилофолат": "Метилфолат",
            "фолат": "Метилфолат",
            "metafolin": "Метилфолат",
            "methylfolate": "Метилфолат",
            "5-mthf": "Метилфолат",
            "ашваганд": "Ашвагандха",
            "коллаген": "Коллаген",
            "витамины": None,  # общее слово — только в комбинации с другими
        }
        text_lower_pre = text.lower().strip()
        # Разбиваем на слова и ищем совпадения с ключами (по целым словам)
        words = text_lower_pre.split()
        pre_found = {}
        for kw, canonical in _SUPPLEMENT_KEYWORDS.items():
            if canonical is None:
                continue
            # Проверяем через contains для многословных ключей (растительные стеролы)
            if kw in text_lower_pre and canonical not in pre_found.values():
                pre_found[kw] = canonical
        # Применяем pre-check только если хотя бы один супплемент найден и часть слов = ключевые
        if pre_found and len(text.split()) <= 6:  # Короткое сообщение с витаминами
            unique_supplements = list(dict.fromkeys(pre_found.values()))
            router_result = {"type": "vitamins", "data": {"items": unique_supplements}}
            debug_logger.info(f"✅ Supplement pre-check found: {unique_supplements}")

    if not router_result:
        # Conversational pre-filter: skip the Sonnet-4.5 LLM router for
        # texts that are clearly questions (saves ~$0.04/message — see
        # core/llm_usage admin panel). Heuristic: ends with '?' or starts
        # with a question word, AND has no food keywords / weight units /
        # supplement names. Conservative — false negative (food sent to
        # agent) is fine because agent will refuse to log; false positive
        # (question sent to router) is fine because router returns 'other'
        # and we route to agent anyway.
        if _is_clearly_conversational(text):
            debug_logger.info("⚡ Pre-filter: conversational text, skipping LLM router")
            router_result = {"type": "other", "data": {}}
        else:
            try:
                debug_logger.info("⏳ Calling analyze_message in executor...")
                loop = asyncio.get_running_loop()
                router_result = await loop.run_in_executor(
                    None, lambda: analyze_message(text=text, user_id=int(user_id))
                )
                debug_logger.info(
                    f"✅ analyze_message returned type: {router_result.get('type') if router_result else 'None'}"
                )
            except Exception as e:
                debug_logger.error(f"❌ analyze_message FAILED: {e}", exc_info=True)
                logger.error(f"LLM Router Error: {e}", exc_info=True)
                router_result = None

    if not router_result:
        # Fallback: Regex for Vitamins
        # from core.health.supplements import supplement_service (DEPRECATED)

        # Simple keywords mapping
        vitamin_map = {
            "омега": "Омега 3-6-9",
            "омегу": "Омега 3-6-9",
            "omega": "Омега 3-6-9",
            "д3": "Витамин D3",
            "d3": "Витамин D3",
            "витамин д": "Витамин D3",
            # Plant Sterols — через Е (стерол) И (стирол) и латиницей
            "стирол": "Plant Sterols",
            "стиролы": "Plant Sterols",
            "стерол": "Plant Sterols",
            "стеролы": "Plant Sterols",
            "растительные стеролы": "Plant Sterols",
            "растительные стиролы": "Plant Sterols",
            "plant sterol": "Plant Sterols",
            "sterol": "Plant Sterols",
            "sterols": "Plant Sterols",
            "магний": "Магний",
            "magne": "Магний",
            "цинк": "Цинк",
            "zinc": "Цинк",
            "псиллиум": "Псиллиум",
            "псилиум": "Псиллиум",
            "psyllium": "Псиллиум",
            "ашваганд": "Ашвагандха",
        }

        found_items = []
        text_lower = text.lower()
        for kw, name in vitamin_map.items():
            if kw in text_lower:
                if name not in found_items:
                    found_items.append(name)

        if found_items:
            logger.info(f"Regex Fallback found vitamins: {found_items}")
            router_result = {"type": "vitamins", "data": {"items": found_items}}
        else:
            await processing_msg.edit_text(
                "🤷‍♂️ Не понял, что это. Это еда? Попробуй описать точнее.\n⚠️ <b>OpenAI не отвечает</b> — доложи баланс в OpenAI или проверь ключ."
            )
            return

    # Wrap the rest in try..except to catch formatting/sending errors
    try:
        msg_type = router_result.get("type")
        data = router_result.get("data", {})

        # Логируем raw text для не-BotkinClaw веток (food / vitamins / bp / weight / ...).
        # BotkinClaw-ветка ('other') сама пишет user-turn внутри ask_agent.
        # См. core.agent_chat.log_router_raw_text — продукт-ревью увидит исходные
        # формулировки пользователя даже когда они распарсились в нутришн/витамины.
        if msg_type and msg_type != "other":
            try:
                from core.agent_chat import log_router_raw_text

                log_router_raw_text(int(user_id), text, msg_type)
            except Exception as _e:
                debug_logger.warning(f"raw text log failed: {_e}")

        if msg_type == "other":
            # BotkinClaw (in-process agent) — route conversational text to
            # core.agent_chat.ask_agent (Claude Messages API + tools). См. ADR-0002
            # о причинах выбора в пользу in-process подхода вместо NanoClaw.
            try:
                from core.agent_chat import ask_agent
                from core.tg_markdown import md_to_html, split_markdown_for_telegram

                # Прогресс-индикатор: реальное сообщение которое edit'им из
                # progress_cb по ходу. Без него юзер видит 12-18 сек тишины.
                progress_msg = await message.answer("⏳ принял...")
                loop = asyncio.get_running_loop()

                # Дроссель: Telegram режет editMessageText >1/сек по chat_id
                # с погрешностью. Не больше 1 edit в 800мс — иначе словим 429.
                import time as _time

                _last_edit = {"t": 0.0, "text": ""}

                def _progress(label: str) -> None:
                    now = _time.monotonic()
                    if now - _last_edit["t"] < 0.8:
                        return
                    if label == _last_edit["text"]:
                        return
                    _last_edit["t"] = now
                    _last_edit["text"] = label
                    # edit_message_text — синхронный вызов из run_in_executor
                    # потока. Используем bot из контекста message.
                    try:
                        import asyncio as _asyncio

                        coro = message.bot.edit_message_text(
                            chat_id=progress_msg.chat.id,
                            message_id=progress_msg.message_id,
                            text=f"⏳ {label}…",
                        )
                        # Кидаем в event loop основного потока (мы в executor)
                        _asyncio.run_coroutine_threadsafe(coro, loop)
                    except Exception as _e:
                        debug_logger.warning(f"progress edit failed: {_e}")

                reply = await loop.run_in_executor(None, ask_agent, int(user_id), text, _progress)
                if not reply:
                    reply = "Хм, у меня нет внятного ответа. Попробуй переформулировать."

                # Финальный ответ кладём в плейсхолдер (первый чанк edit'ом,
                # остальные новыми сообщениями).
                chunks = split_markdown_for_telegram(reply)

                async def _send_chunk(chunk: str, edit_target=None):
                    chunk_html = md_to_html(chunk)
                    try:
                        if edit_target is not None:
                            await message.bot.edit_message_text(
                                chat_id=edit_target.chat.id,
                                message_id=edit_target.message_id,
                                text=chunk_html,
                                parse_mode="HTML",
                            )
                        else:
                            await message.answer(chunk_html, parse_mode="HTML")
                    except Exception as html_err:
                        debug_logger.warning(f"HTML render failed ({html_err}); falling back to plain")
                        if edit_target is not None:
                            await message.bot.edit_message_text(
                                chat_id=edit_target.chat.id,
                                message_id=edit_target.message_id,
                                text=chunk,
                            )
                        else:
                            await message.answer(chunk)

                for i, chunk in enumerate(chunks):
                    await _send_chunk(chunk, edit_target=progress_msg if i == 0 else None)
            except RuntimeError as e:
                # Common: user has no agent_system_prompt → conversational
                # mode not enabled for them yet. Fall back to canned reply.
                if "agent_system_prompt" in str(e):
                    debug_logger.info(f"agent_chat skipped: {e}")
                    fallback = data.get("reply", "Не понял запрос.")
                    await message.answer(html.escape(fallback))
                else:
                    debug_logger.error(f"agent_chat failed: {e}", exc_info=True)
                    await message.answer("🤖 Разговорный агент временно недоступен. Попробуй через минуту.")
            except Exception as e:
                debug_logger.error(f"agent_chat exception: {e}", exc_info=True)
                err_str = str(e).lower()
                if any(code in err_str for code in ("529", "503", "overloaded", "rate")):
                    await message.answer(
                        "⏳ AI-провайдер сейчас перегружен. Попробуй через минуту — данные не пропали."
                    )
                elif "429" in err_str:
                    await message.answer("⏳ Слишком много запросов подряд. Подожди пару минут.")
                else:
                    await message.answer("🤖 Что-то сломалось при ответе. Попробуй ещё раз.")
            return

        elif msg_type == "vitamins":
            items = data.get("items", [])

            # Нормализуем имена витаминов перед сохранением
            _NORMALIZE = {
                "стирол": "Plant Sterols",
                "стиролы": "Plant Sterols",
                "стерол": "Plant Sterols",
                "стеролы": "Plant Sterols",
                "растительные стеролы": "Plant Sterols",
                "растительные стиролы": "Plant Sterols",
                "plant sterol": "Plant Sterols",
                "sterols": "Plant Sterols",
                "омега": "Омега 3",
                "омега-3": "Омега 3",
                "omega": "Омега 3",
                "омега 3-6-9": "Омега 3",
                "ѓ3": "Витамин D3",
                "d3": "Витамин D3",
                "витамин д": "Витамин D3",
                "витамин d": "Витамин D3",
                "псилиум": "Псиллиум",
                "psyllium": "Псиллиум",
                "creatine": "Креатин",
                "kreatin": "Креатин",
                "кретин": "Креатин",
                "моногидрат": "Креатин",
                "creatine monohydrate": "Креатин",
            }

            # Определяем: писал ли пользователь «оба стирола» или «обема стиролы»
            text_lower_v = text.lower()
            both_sterols = any(
                kw in text_lower_v
                for kw in [
                    "оба стир",
                    "оба стер",
                    "обема стир",
                    "обема стер",
                    "обоих стир",
                    "обоих стер",
                    "both sterol",
                ]
            )

            normalized = []
            has_plain_sterols = False
            for item in items:
                key = item.strip().lower()
                canonical = _NORMALIZE.get(key, item)
                if canonical == "Plant Sterols":
                    has_plain_sterols = True
                elif canonical not in normalized:
                    normalized.append(canonical)

            # Plant Sterols: если «оба» — разворачиваем в утро + вечер; если просто один — только Plant Sterols
            if has_plain_sterols:
                if both_sterols:
                    normalized.append("Plant Sterols (Утро)")
                    normalized.append("Plant Sterols (Вечер)")
                else:
                    normalized.append("Plant Sterols")

            items = normalized

            # Сохраняем реально
            from core.health.supplements import save_supplements

            telegram_user_id = int(message.from_user.id)
            saved = save_supplements(items, user_id=telegram_user_id, date_str=custom_date)

            # Формируем красивый список
            items_list = "\n".join([f"• {html.escape(str(item))}" for item in items])

            status_text = "✅ <b>Записано</b>" if saved else "⚠️ <b>Ошибка записи</b>"

            response = f"💊 <b>Витамины:</b>\n{items_list}\n\n{status_text}"

            await processing_msg.edit_text(response, parse_mode="HTML")
            return

        elif msg_type == "mixed":
            # Смешанное сообщение: еда (протеин с граммами) + добавки (креатин, магний и т.п.)
            food_data = data.get("food", {})
            supplement_items = data.get("supplements", [])

            # 1. Сохраняем добавки (нормализация — та же что в vitamins)
            _NORMALIZE_MX = {
                "стирол": "Plant Sterols",
                "стиролы": "Plant Sterols",
                "стерол": "Plant Sterols",
                "стеролы": "Plant Sterols",
                "растительные стеролы": "Plant Sterols",
                "растительные стиролы": "Plant Sterols",
                "plant sterol": "Plant Sterols",
                "sterols": "Plant Sterols",
                "омега": "Омега 3",
                "омега-3": "Омега 3",
                "omega": "Омега 3",
                "ѓ3": "Витамин D3",
                "d3": "Витамин D3",
                "витамин д": "Витамин D3",
                "витамин d": "Витамин D3",
                "псилиум": "Псиллиум",
                "psyllium": "Псиллиум",
                "creatine": "Креатин",
                "kreatin": "Креатин",
                "кретин": "Креатин",
                "monohydrate": "Креатин",
                "creatine monohydrate": "Креатин",
                "magnesium": "Магний",
            }
            normalized_supp = []
            for item in supplement_items:
                key = item.strip().lower()
                canonical = _NORMALIZE_MX.get(key, item)
                if canonical not in normalized_supp:
                    normalized_supp.append(canonical)

            from core.health.supplements import save_supplements

            telegram_user_id = int(message.from_user.id)
            supp_saved = (
                save_supplements(normalized_supp, user_id=telegram_user_id, date_str=custom_date)
                if normalized_supp
                else True
            )

            # 2. Обрабатываем еду через стандартный food pipeline
            if food_data and food_data.get("items"):
                food_router_result = {"type": "food", "data": food_data}
                meal_items, meal_totals = await loop.run_in_executor(
                    None, process_llm_food_data, food_router_result, text
                )
            else:
                meal_items, meal_totals = [], {}

            # 3. Ответ: добавки сразу, еда — через confirmation
            if not meal_items:
                # Еда не распозналась — показываем только добавки
                supp_list = "\n".join([f"• {html.escape(str(s))}" for s in normalized_supp])
                await processing_msg.edit_text(
                    f"💊 <b>Добавки записаны:</b>\n{supp_list}\n\n⚠️ Еду не удалось распознать, введи отдельно.",
                    parse_mode="HTML",
                )
                return

            # Еда распозналась — создаём confirmation state и добавляем добавки в данные
            meal_name = food_data.get("dish_name") or food_data.get("meal_type") or "Приём пищи"
            from services.state import UserState

            new_state = UserState(
                user_id=user_id,
                state="waiting_confirmation",
                data={
                    "description": text,
                    "meal_items": meal_items,
                    "meal_totals": meal_totals,
                    "meal_time": datetime.now(MSK).strftime("%H:%M"),
                    "meal_name": meal_name,
                    "date": custom_date,
                },
            )
            state_manager.set_state(user_id, new_state)

            # Показываем добавки + еду с кнопками подтверждения
            supp_list = "\n".join([f"• {html.escape(str(s))}" for s in normalized_supp])
            supp_status = "✅" if supp_saved else "⚠️"
            response = f"💊 {supp_status} <b>Добавки:</b>\n{supp_list}\n\n"
            response += f"🍽️ <b>{html.escape(str(meal_name))}</b>\n"
            for item in meal_items:
                w_str = f"{item['weight_g']}г" if item.get("weight_g") else "?"
                cal = item.get("calories", 0)
                p = int(item.get("protein", 0))
                f_val = int(item.get("fats", 0))
                c = int(item.get("carbs", 0))
                response += (
                    f"• {html.escape(str(item['product']))} ({w_str}) — {int(cal)} ккал (Б:{p} Ж:{f_val} У:{c})\n"
                )
            response += f"\n📊 <b>Итого: {int(meal_totals['calories'])} ккал</b>\n"
            response += (
                f"Б: {int(meal_totals['protein'])} | Ж: {int(meal_totals['fats'])} | У: {int(meal_totals['carbs'])}"
            )
            from core.food.nutrition import format_kcal_warning

            response += format_kcal_warning(meal_totals)

            from handlers.callbacks import MealConfirmationCallback
            from aiogram.utils.keyboard import InlineKeyboardBuilder

            builder = InlineKeyboardBuilder()
            builder.button(
                text="✅ Записать", callback_data=MealConfirmationCallback(action="confirm", user_id=user_id).pack()
            )
            builder.button(
                text="❌ Отмена", callback_data=MealConfirmationCallback(action="cancel", user_id=user_id).pack()
            )
            builder.adjust(2)

            await processing_msg.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
            return

        elif msg_type == "weight":
            w_val = data.get("weight")
            await processing_msg.edit_text(f"⚖️ <b>Вес:</b> {w_val} кг\n✅ Записано (Simulated)", parse_mode="HTML")
            return

        elif msg_type == "body_measurements":
            # Обработка замеров тела
            data = router_result.get("data", {})
            from helpers.db_save import save_body_measurement_to_db

            telegram_user_id = int(message.from_user.id)
            saved = save_body_measurement_to_db(data, user_id=telegram_user_id)

            # Формируем ответ
            m_parts = []
            if data.get("waist_cm"):
                m_parts.append(f"Талия: {data['waist_cm']} см")
            if data.get("neck_cm"):
                m_parts.append(f"Шея: {data['neck_cm']} см")
            if data.get("hips_cm"):
                m_parts.append(f"Бедра: {data['hips_cm']} см")
            if data.get("chest_cm"):
                m_parts.append(f"Грудь: {data['chest_cm']} см")
            if data.get("thigh_cm"):
                m_parts.append(f"Бедро: {data['thigh_cm']} см")
            if data.get("biceps_cm"):
                m_parts.append(f"Бицепс: {data['biceps_cm']} см")

            m_list = "\n".join([f"• {p}" for p in m_parts])
            status_text = "✅ <b>Записано</b>" if saved else "⚠️ <b>Ошибка записи</b>"

            response = f"📏 <b>Замеры тела:</b>\n{m_list}\n\n{status_text}"

            await processing_msg.edit_text(response, parse_mode="HTML")
            return

        elif msg_type == "food":
            # ЕДА
            # process_llm_food_data is synchronous and might block loop (requests to OpenAI)
            # Run it in executor to keep bot responsive
            # loop is already defined at top of function

            debug_logger.info("⏳ Running process_llm_food_data in executor...")

            # Using run_in_executor to not block the main loop
            meal_items, meal_totals = await loop.run_in_executor(None, process_llm_food_data, router_result, text)
            debug_logger.info(f"✅ process_llm_food_data finished in executor. Items: {len(meal_items)}")

            if not meal_items:
                await processing_msg.edit_text("❌ Вроде еда, но продуктов не нашел.")
                return

            meal_name = data.get("dish_name") or data.get("meal_type")
            if not meal_name:
                meal_name = extract_meal_name(text, datetime.now(MSK).strftime("%H:%M"))
            meal_name = apply_slot_prefix(text, meal_name)

            # Создаем состояние confirmation
            from services.state import UserState

            new_state = UserState(
                user_id=user_id,
                state="waiting_confirmation",
                data={
                    "description": text,
                    "meal_items": meal_items,
                    "meal_totals": meal_totals,
                    "meal_time": datetime.now(MSK).strftime("%H:%M"),
                    "meal_name": meal_name,
                    "date": custom_date,
                },
            )
            state_manager.set_state(user_id, new_state)

            # Формируем заголовок с датой, если это не сегодня
            # Escape meal_name!
            safe_meal_name = html.escape(str(meal_name))

            header = f"🍽️ <b>{safe_meal_name}</b>"
            if custom_date:
                # Парсим дату и форматируем красиво
                try:
                    # datetime imported globally
                    date_obj = datetime.strptime(custom_date, "%Y-%m-%d")
                    # Названия дней недели на русском
                    weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
                    weekday = weekdays_ru[date_obj.weekday()]
                    formatted_date = date_obj.strftime("%d.%m.%Y")
                    header = f"🍽️ <b>{safe_meal_name} в {weekday} {formatted_date}</b>"
                except:
                    # Если не удалось распарсить, просто показываем дату
                    header = f"🍽️ <b>{safe_meal_name} ({custom_date})</b>"

            # Формируем ответ
            response = f"{header}\n\n"
            for item in meal_items:
                w_str = f"{item['weight_g']}г" if item.get("weight_g") else "?"
                cal = item.get("calories", 0)
                p = int(item.get("protein", 0))
                f = int(item.get("fats", 0))
                c = int(item.get("carbs", 0))

                # Escape product name
                safe_product = html.escape(str(item["product"]))

                response += f"• {safe_product} ({w_str}) — {int(cal)} ккал (Б:{p} Ж:{f} У:{c})\n"

            response += f"\n📊 <b>Итого: {int(meal_totals['calories'])} ккал</b>\n"
            response += (
                f"Б: {int(meal_totals['protein'])} | Ж: {int(meal_totals['fats'])} | У: {int(meal_totals['carbs'])}"
            )
            from core.food.nutrition import format_kcal_warning

            response += format_kcal_warning(meal_totals)

            # Buttons
            from handlers.callbacks import MealConfirmationCallback
            from aiogram.utils.keyboard import InlineKeyboardBuilder

            builder = InlineKeyboardBuilder()
            builder.button(
                text="✅ Сохранить", callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack()
            )
            builder.button(
                text="❌ Отмена", callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack()
            )

            await processing_msg.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
            return

        else:
            await processing_msg.edit_text(f"🤔 Тип сообщения: {msg_type}, но я пока не знаю что с этим делать.")

    except Exception as e:
        logger.error(f"❌ Error processing message: {e}", exc_info=True)
        error_text = f"❌ Произошла ошибка при обработке:\n<pre>{html.escape(str(e))}</pre>\n\nПопробуй еще раз или напиши разработчику."
        await processing_msg.edit_text(error_text, parse_mode="HTML")


@router.message(F.video_note)
async def handle_video_note(message: Message, state: FSMContext):
    """Обработчик видеосообщений"""
    await message.answer("📹 Видеосообщения пока не поддерживаются. Отправь фото или текстовое описание.")
