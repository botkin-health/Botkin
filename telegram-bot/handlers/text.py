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

    # Регулярка для "29-го января" или "29 января"
    text_date_match = re.search(r"^(\d{1,2})(?:-?го)?\s+([а-я]+)", text_lower)
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
                clean_text = text[text_date_match.end() :].strip()
                clean_text = re.sub(r"^[:,\-\s]+", "", clean_text).strip()
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
    from core.llm_router import analyze_message
    from core.nutrition import process_llm_food_data
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

    # Отправляем сообщение "Думаю..."
    processing_msg = await message.answer("🤖 Читаю и анализирую... 🧠")
    debug_logger.info("✅ Sent 'Thinking' message")

    # Извлекаем дату "Вчера" если есть, для контекста
    from handlers.text import extract_date_from_text

    custom_date, clean_text = extract_date_from_text(text)
    if custom_date:
        text = clean_text

    # Сначала проверяем "мои продукты" — без вызова нейросети
    router_result = None
    from database import SessionLocal, match_user_product

    db = SessionLocal()
    try:
        telegram_id = int(message.from_user.id)
        matched = match_user_product(db, telegram_id, text)
        if matched:
            # Напитки без калорий: по названию продукта или по тексту ("coca-cola zero") — принудительно 0
            from core.description_parser import is_zero_calorie_drink

            if is_zero_calorie_drink(matched["name"]) or is_zero_calorie_drink(text):
                matched = {**matched, "calories": 0, "protein": 0, "fats": 0, "carbs": 0}
            router_result = {
                "type": "food",
                "data": {
                    "dish_name": matched["name"],
                    "meal_type": "snack",
                    "items": [
                        {
                            "name": matched["name"],
                            "weight": matched["weight_g"],
                            "quantity": None,
                            "calories": matched["calories"],
                            "protein": matched["protein"],
                            "fats": matched["fats"],
                            "carbs": matched["carbs"],
                        }
                    ],
                    "total_nutrition": {
                        "calories": matched["calories"],
                        "protein": matched["protein"],
                        "fats": matched["fats"],
                        "carbs": matched["carbs"],
                    },
                },
            }
            debug_logger.info(f"✅ Найден свой продукт: {matched['name']} {matched['weight_g']}г")
    finally:
        db.close()

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
        try:
            debug_logger.info("⏳ Calling analyze_message in executor...")
            loop = asyncio.get_running_loop()
            router_result = await loop.run_in_executor(None, analyze_message, text)
            debug_logger.info(
                f"✅ analyze_message returned type: {router_result.get('type') if router_result else 'None'}"
            )
        except Exception as e:
            debug_logger.error(f"❌ analyze_message FAILED: {e}", exc_info=True)
            logger.error(f"LLM Router Error: {e}", exc_info=True)
            router_result = None

    if not router_result:
        # Fallback: Regex for Vitamins
        # from core.supplements import supplement_service (DEPRECATED)

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

        if msg_type == "other":
            reply = data.get("reply", "Не понял запрос.")
            # Escape reply just in case
            await processing_msg.edit_text(html.escape(reply))
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
            from core.supplements import save_supplements

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

            from core.supplements import save_supplements

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
