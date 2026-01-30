#!/usr/bin/env python3
"""
Обработчик текстовых сообщений и голосовых сообщений
"""

import re
import json
from pathlib import Path
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from services.state import state_manager, UserState

router = Router()

# Определяем корневую директорию HealthVault
HEALTHVAULT_ROOT = Path(__file__).parent.parent.parent
NUTRITION_LOG_JSON = HEALTHVAULT_ROOT / 'data' / 'nutrition' / 'nutrition_log.json'


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
        r'\d+\s*(г|грамм|граммов|кг|килограмм)',
        r'\d+\s*(мл|миллилитр|л|литр)',
        r'\d+\s*(ч\.?\s*л\.?|чайн\w*\s*лож\w*|столов\w*\s*лож\w*)',
        r'\d+\s*(стакан|чашк|тарелк|порци)',
        r'\d+\s*(штук|шт\.?|кусоч|ломтик)',
        
        # Описание времени приема пищи
        r'(завтрак|обед|ужин|перекус|бранч|полдник)\s*[:\-]',
        r'(на\s+)?(завтрак|обед|ужин|перекус)',
        r'(утром|днем|вечером|ночью)\s*(ел|съел|поел)',
        
        # Указания на прием пищи во времени  
        r'(вчера|сегодня|позавчера)\s+(завтрак|обед|ужин|перекус|ел|съел)',
        r'(завтрак|обед|ужин|перекус)\s+(вчера|сегодня)',
        
        # Процессы приготовления
        r'(варен\w*|жарен\w*|тушен\w*|печен\w*|сыр\w*)',
        r'(приготовил|готовил|сделал|смешал)\s'
    ]
    
    # Продукты питания (средние индикаторы)
    food_keywords = [
        'яйц', 'курин', 'мяс', 'рыб', 'сыр', 'молок', 'творог', 'йогурт',
        'хлеб', 'каш', 'рис', 'греч', 'овся', 'макарон', 'спагетти', 
        'картофел', 'овощ', 'помидор', 'огурец', 'лук', 'морков', 'капуст',
        'яблок', 'банан', 'апельсин', 'фрукт', 'ягод',
        'масл', 'соус', 'солен', 'сахар', 'мед',
        'печень', 'орех', 'семеч', 'крупа', 'бобов'
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
    if re.search(r'\d+.*(?:г|грамм|мл|ложк|стакан|штук|кусоч|порци)', text_lower) and len(text) > 10:
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
        (r'^(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)\s*[:]', 'ru'),  # "обед: яичница..."
        (r'как\s+(?:мой|мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)', 'ru'),
        (r'это\s+(?:мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)', 'ru'),  # "да, это завтрак"
        (r'(?:мой\s+)?(завтрак|обед|ужин|перекус|бранч|полдник|ранний\s+ужин|вечерний\s+перекус)', 'ru'),
        (r'^(breakfast|lunch|dinner|snack|brunch)\s*[:]', 'en'),  # "lunch: ..."
        (r'for\s+(?:my\s+)?(breakfast|lunch|dinner|snack|brunch)', 'en'),  # "for dinner I mixed..."
        (r'(?:as\s+)?(?:my\s+)?(breakfast|lunch|dinner|snack|brunch)', 'en'),
    ]
    
    for pattern, lang in meal_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            meal_name = match.group(1)
            # Капитализуем первую букву
            if lang == 'ru':
                # Русские названия
                meal_map = {
                    'завтрак': 'Завтрак',
                    'обед': 'Обед',
                    'ужин': 'Ужин',
                    'перекус': 'Перекус',
                    'бранч': 'Бранч',
                    'полдник': 'Полдник',
                    'ранний ужин': 'Ранний ужин',
                    'вечерний перекус': 'Вечерний перекус',
                }
                return meal_map.get(meal_name, meal_name.capitalize())
            else:
                # Английские названия
                meal_map = {
                    'breakfast': 'Завтрак',
                    'lunch': 'Обед',
                    'dinner': 'Ужин',
                    'snack': 'Перекус',
                    'brunch': 'Бранч',
                }
                return meal_map.get(meal_name.lower(), meal_name.capitalize())
    
    # Если не найдено в тексте, определяем по времени суток
    if meal_time:
        try:
            hour = int(meal_time.split(':')[0])
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
    
    # Если время не указано, используем текущее время
    current_hour = datetime.now().hour
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
    
    # Ключевые слова для "вчера"
    yesterday_keywords = ['вчера', 'yesterday']
    
    # Проверяем начало строки
    # Например: "Вчера ужин: ..." или "Вчера: ..."
    # 1. Проверка "вчера" / "yesterday"
    for kw in yesterday_keywords:
        if text_lower.startswith(kw):
            # Проверяем, что идет после ключевого слова
            after_kw = text_lower[len(kw):]
            
            # Если текст закончился - это просто "вчера"
            if not after_kw:
                yesterday = datetime.now() - timedelta(days=1)
                date_str = yesterday.strftime('%Y-%m-%d')
                return date_str, ''
                
            # Если после ключевого слова идет разделитель
            if after_kw[0] in [':', ',', '-', ' ', '\n']:
                yesterday = datetime.now() - timedelta(days=1)
                date_str = yesterday.strftime('%Y-%m-%d')
                
                clean_text = text[len(kw):].strip()
                clean_text = re.sub(r'^[:,\-\s]+', '', clean_text).strip()
                return date_str, clean_text

    # 2. Проверка даты в формате ДД.ММ или ДД/ММ (например "29.01", "29/01")
    # Ищем в начале строки
    date_match = re.match(r'^(\d{1,2})[./](\d{1,2})\s*', text_lower)
    if date_match:
        day, month = int(date_match.group(1)), int(date_match.group(2))
        try:
            # Предполагаем текущий год. Если месяц больше текущего - значит прошлый год?
            # Нет, просто текущий год для простоты, или умная логика
            current_year = datetime.now().year
            # Если дата в будущем (например, сегодня 01.02, а ввели 29.01) - это ок
            # Если сегодня 01.01, а ввели 31.12 - это прошлый год
            
            # Простая логика: используем текущий год
            target_date = datetime(current_year, month, day)
            
            # Если полученная дата в будущем (более чем на 1 день), то скорее всего имели в виду прошлый год
            if target_date > datetime.now() + timedelta(days=1):
                target_date = datetime(current_year - 1, month, day)
                
            date_str = target_date.strftime('%Y-%m-%d')
            clean_text = text[date_match.end():].strip()
            # Убираем разделители, если остались
            clean_text = re.sub(r'^[:,\-\s]+', '', clean_text).strip()
            return date_str, clean_text
        except ValueError:
            pass # Invalid date

    # 3. Проверка даты текстом (например "29 января", "29-го января")
    months = {
        'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'мая': 5, 'май': 5, 'июн': 6,
        'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12
    }
    
    # Регулярка для "29-го января" или "29 января"
    text_date_match = re.search(r'^(\d{1,2})(?:-?го)?\s+([а-я]+)', text_lower)
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
                current_year = datetime.now().year
                target_date = datetime(current_year, month, day)
                
                # Коррекция года
                if target_date > datetime.now() + timedelta(days=1):
                    target_date = datetime(current_year - 1, month, day)
                
                date_str = target_date.strftime('%Y-%m-%d')
                clean_text = text[text_date_match.end():].strip()
                clean_text = re.sub(r'^[:,\-\s]+', '', clean_text).strip()
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
        r'^(да|yes|сохрани|save|ок|ok|хорошо|сохранить)',
        r'^(да|yes).*сохрани',
        r'сохрани.*(да|yes)',
    ]
    
    for pattern in confirm_patterns:
        if re.match(pattern, text_lower):
            return True
    
    return False


def save_meal_to_json(meal_data: dict, meal_name: str = None):
    """
    Сохраняет приём пищи в nutrition_log.json
    
    Args:
        meal_data: Данные о приёме пищи из состояния
        meal_name: Название приёма пищи (если None, используется из meal_data или "Приём пищи")
    """
    # Определяем дату: берем из meal_data или используем сегодня
    custom_date = meal_data.get('date')
    today = custom_date if custom_date else datetime.now().strftime('%Y-%m-%d')
    
    # Загружаем существующие данные
    if NUTRITION_LOG_JSON.exists():
        try:
            with open(NUTRITION_LOG_JSON, 'r', encoding='utf-8') as f:
                nutrition_data = json.load(f)
        except Exception as e:
            print(f"Ошибка при загрузке nutrition_log.json: {e}")
            nutrition_data = {'entries': []}
    else:
        nutrition_data = {'entries': []}
    
    # Ищем запись за сегодня
    today_entry = None
    for entry in nutrition_data.get('entries', []):
        if entry.get('date') == today:
            today_entry = entry
            break
    
    if not today_entry:
        today_entry = {
            'date': today,
            'had_workout': False,
            'meals': [],
            'totals': {
                'calories': 0.0,
                'protein': 0.0,
                'fats': 0.0,
                'carbs': 0.0,
            }
        }
        nutrition_data.setdefault('entries', []).append(today_entry)
    
    # Формируем данные приёма пищи
    meal_items = meal_data.get('meal_items', [])
    meal_totals = meal_data.get('meal_totals', {})
    meal_time = meal_data.get('meal_time', datetime.now().strftime('%H:%M'))
    
    # Используем название из параметра или из данных
    if not meal_name:
        meal_name = meal_data.get('dish_name') or meal_data.get('meal_name')
        # Если всё ещё нет, определяем по времени
        if not meal_name or meal_name == "Приём пищи":
            meal_name = extract_meal_name(meal_data.get('description', ''), meal_time)
    
    # Формируем items в нужном формате
    items = []
    for item in meal_items:
        items.append({
            'food': item.get('product', 'Неизвестный продукт'),
            'amount': item.get('weight_g', 0.0),
            'unit': 'г',
            'calories': int(round(item.get('calories', 0.0))),
            'protein': int(round(item.get('protein', 0.0))),
            'fats': int(round(item.get('fats', 0.0))),
            'carbs': int(round(item.get('carbs', 0.0))),
        })
    
    # Добавляем приём пищи
    new_meal = {
        'meal': meal_name,
        'time': meal_time,
        'items': items,
    }
    today_entry['meals'].append(new_meal)
    
    # Обновляем totals
    totals = today_entry['totals']
    totals['calories'] = int(round(totals.get('calories', 0.0) + meal_totals.get('calories', 0.0)))
    totals['protein'] = int(round(totals.get('protein', 0.0) + meal_totals.get('protein', 0.0)))
    totals['fats'] = int(round(totals.get('fats', 0.0) + meal_totals.get('fats', 0.0)))
    totals['carbs'] = int(round(totals.get('carbs', 0.0) + meal_totals.get('carbs', 0.0)))
    
    # Сохраняем
    try:
        with open(NUTRITION_LOG_JSON, 'w', encoding='utf-8') as f:
            json.dump(nutrition_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка при сохранении в nutrition_log.json: {e}")
        return False


@router.message(F.text & ~F.photo)
async def handle_text(message: Message, state: FSMContext):
    """Обработчик текстовых сообщений (БЕЗ фото)"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Не обрабатываем команды (они обрабатываются в handlers/commands.py)
    if message.text and message.text.startswith('/'):
        logger.debug(f"Пропущена команда: {message.text}")
        return
    
    # Дополнительная проверка на случай, если фильтр не сработал
    if message.photo:
        logger.warning(f"⚠️ Обработчик текста получил сообщение с фото - пропускаем")
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
    if user_state and user_state.state == 'waiting_description':
        # Обрабатываем как описание блюда
        from handlers.photo import handle_description
        await handle_description(message, message.text)
        return
    
    # --- LLM Router Logic ---
    from core.llm_router import analyze_message
    from core.nutrition import process_llm_food_data
    
    # Отправляем сообщение "Думаю..."
    processing_msg = await message.answer("🤖 Читаю и анализирую... 🧠")
    
    text = message.text.strip()
    
    # Извлекаем дату "Вчера" если есть, для контекста
    from handlers.text import extract_date_from_text
    custom_date, clean_text = extract_date_from_text(text)
    if custom_date:
        text = clean_text
    
    try:
        router_result = analyze_message(text=text)
    except Exception as e:
        logger.error(f"LLM Router Error: {e}")
        router_result = None
        
    if not router_result:
        # Fallback: Regex for Vitamins
        from core.supplements import supplement_service
        # Simple keywords mapping
        vitamin_map = {
            'омега': 'Омега 3-6-9',
            'омегу': 'Омега 3-6-9',
            'omega': 'Омега 3-6-9',
            'д3': 'Витамин D3',
            'd3': 'Витамин D3',
            'витамин д': 'Витамин D3',
            'стирол': 'Plant Sterols',
            'стерол': 'Plant Sterols',
            'sterol': 'Plant Sterols',
            'магний': 'Магний',
            'magne': 'Магний',
            'цинк': 'Цинк',
            'zinc': 'Цинк',
            'псиллиум': 'Псиллиум',
            'псилиум': 'Псиллиум',
            'psyllium': 'Псиллиум',
            'ашваганд': 'Ашвагандха',
        }
        
        found_items = []
        text_lower = text.lower()
        for kw, name in vitamin_map.items():
            if kw in text_lower:
                if name not in found_items:
                    found_items.append(name)
        
        if found_items:
            logger.info(f"Regex Fallback found vitamins: {found_items}")
            router_result = {
                'type': 'vitamins',
                'data': {'items': found_items}
            }
        else:
            await processing_msg.edit_text("🤷‍♂️ Не понял, что это. Это еда? Попробуй описать точнее.\n⚠️ <b>OpenAI не отвечает</b> (возможно, выключен VPN или проблема с ключом).")
            return

    msg_type = router_result.get('type')
    data = router_result.get('data', {})

    if msg_type == 'other':
        reply = data.get('reply', 'Не понял запрос.')
        await processing_msg.edit_text(reply)
        return

    elif msg_type == 'vitamins':
        items = data.get('items', [])
        
        # Сохраняем реально
        from core.supplements import save_supplements
        telegram_user_id = int(message.from_user.id)
        saved = save_supplements(items, user_id=telegram_user_id, date_str=custom_date)
        
        # Формируем красивый список
        items_list = "\n".join([f"• {item}" for item in items])
        
        status_text = "✅ <b>Записано</b>" if saved else "⚠️ <b>Ошибка записи</b>"
        
        response = (
            f"💊 <b>Витамины:</b>\n"
            f"{items_list}\n\n"
            f"{status_text}"
        )
        
        await processing_msg.edit_text(response, parse_mode='HTML')
        return

    elif msg_type == 'weight':
        w_val = data.get('weight')
        await processing_msg.edit_text(f"⚖️ <b>Вес:</b> {w_val} кг\n✅ Записано (Simulated)", parse_mode='HTML')
        return
        
    elif msg_type == 'food':
        # ЕДА
        meal_items, meal_totals = process_llm_food_data(router_result, description=text)
        
        if not meal_items:
             await processing_msg.edit_text("❌ Вроде еда, но продуктов не нашел.")
             return

        meal_name = data.get('dish_name') or data.get('meal_type')
        if not meal_name:
             meal_name = extract_meal_name(text, datetime.now().strftime('%H:%M'))
        
        # Создаем состояние confirmation
        from services.state import UserState
        new_state = UserState(
            user_id=user_id,
            state='waiting_confirmation',
            data={
                'description': text,
                'meal_items': meal_items,
                'meal_totals': meal_totals,
                'meal_time': datetime.now().strftime('%H:%M'),
                'meal_name': meal_name,
                'date': custom_date
            }
        )
        state_manager.set_state(user_id, new_state)
        
        # Формируем ответ
        response = f"🍽️ <b>{meal_name}</b>\n\n"
        for item in meal_items:
            w_str = f"{item['weight_g']}г" if item.get('weight_g') else "?"
            cal = item.get('calories', 0)
            p = int(item.get('protein', 0))
            f = int(item.get('fats', 0))
            c = int(item.get('carbs', 0))
            response += f"• {item['product']} ({w_str}) — {int(cal)} ккал (Б:{p} Ж:{f} У:{c})\n"
            
        response += f"\n📊 <b>Итого: {int(meal_totals['calories'])} ккал</b>\n"
        response += f"Б: {int(meal_totals['protein'])} | Ж: {int(meal_totals['fats'])} | У: {int(meal_totals['carbs'])}"

        # Buttons
        from handlers.callbacks import MealConfirmationCallback
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Сохранить", callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack())
        builder.button(text="❌ Отмена", callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack())
        
        await processing_msg.edit_text(response, parse_mode='HTML', reply_markup=builder.as_markup())
        return

    else:
        await processing_message.edit_text(f"🤔 Тип сообщения: {msg_type}, но я пока не знаю что с этим делать.")





@router.message(F.video_note)
async def handle_video_note(message: Message, state: FSMContext):
    """Обработчик видеосообщений"""
    await message.answer("📹 Видеосообщения пока не поддерживаются. Отправь фото или текстовое описание.")
