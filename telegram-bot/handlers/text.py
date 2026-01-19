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
                # Вычисляем дату вчера
                yesterday = datetime.now() - timedelta(days=1)
                date_str = yesterday.strftime('%Y-%m-%d')
                
                # Очищаем текст от слова "вчера" и разделителей
                clean_text = text[len(kw):].strip()
                clean_text = re.sub(r'^[:,\-\s]+', '', clean_text).strip()
                
                return date_str, clean_text
                
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
    
    # --- ЛОГИКА ДОБАВОК ---
    from core.supplements import supplement_service
    logged_items, remaining_items = supplement_service.log_intake(message.text)
    if logged_items:
        # Если нашли витамины - сохраняем и отвечаем, дальше не идем
        response = f"💊 <b>Сохранено:</b> {', '.join(logged_items)}\n\n"
        if remaining_items:
            response += "⏳ <b>Осталось принять сегодня:</b>\n" + "\n".join(remaining_items)
        else:
            response += "🎉 <b>На сегодня все витамины приняты!</b>"
            
        await message.answer(response)
        return
    # ----------------------
    
    # Проверяем, ожидается ли подтверждение сохранения
    if user_state and user_state.state == 'waiting_confirmation':
        text = message.text.strip()
        is_confirm = is_confirmation(text)
        
        logger.info(f"is_confirmation('{text}') = {is_confirm}")
        
        if is_confirm:
            # Извлекаем название приёма пищи
            meal_name = extract_meal_name(text)
            
            # Сохраняем в JSON
            if save_meal_to_json(user_state.data, meal_name):
                await message.answer(
                    f"✅ <b>Сохранено!</b>\n\n"
                    f"🍽️ <b>{meal_name}</b>\n"
                    f"📊 КБЖУ:\n"
                    f"• Калории: {user_state.data.get('meal_totals', {}).get('calories', 0):.0f} ккал\n"
                    f"• Белки: {user_state.data.get('meal_totals', {}).get('protein', 0):.0f} г\n"
                    f"• Жиры: {user_state.data.get('meal_totals', {}).get('fats', 0):.0f} г\n"
                    f"• Углеводы: {user_state.data.get('meal_totals', {}).get('carbs', 0):.0f} г",
                    parse_mode='HTML'
                )
            else:
                await message.answer("❌ Ошибка при сохранении. Попробуйте ещё раз.")
            
            # Очищаем состояние
            state_manager.clear_state(user_id)
        else:
            # Если не подтверждение, но это похоже на описание еды (длинное, содержит продукты)
            # - обрабатываем как новое описание, сбрасывая старое состояние
            text_lower = text.lower()
            food_keywords = ['яйц', 'сыр', 'лук', 'томат', 'каша', 'греч', 'рис', 'макарон', 'куриц', 'мясо', 'рыб']
            is_food_description = len(text) > 20 and any(keyword in text_lower for keyword in food_keywords)
            
            if is_food_description:
                logger.info(f"Текст похож на описание еды, обрабатываем как новое описание (сбрасываем старое состояние)")
                state_manager.clear_state(user_id)
                # Обрабатываем как новое описание
                from handlers.photo import handle_description
                from services.state import UserState
                
                new_user_state = UserState(
                    user_id=user_id,
                    state='waiting_description',
                    data={
                        'caption': '',  # Не дублируем текст в caption
                        'photo_paths': [],
                        'photo_file_ids': [],
                    }
                )
                state_manager.set_state(user_id, new_user_state)
                await handle_description(message, text)
            else:
                # Если не похоже на описание - напоминаем о кнопках
                await message.answer(
                    "💡 Используй кнопки '✅ Сохранить' или '❌ Не сохранять' для подтверждения.\n"
                    "Или отправь новое описание еды."
                )
    
    # Текстовое сообщение без состояния или с другим состоянием - обрабатываем как описание еды
    else:
        # Текстовое сообщение без фото - обрабатываем как описание еды
        text = message.text.strip()
        
        # Проверяем наличие ключевого слова "Вчера"
        custom_date, clean_text = extract_date_from_text(text)
        
        # Если дата была извлечена, используем очищенный текст
        processing_text = clean_text if custom_date else text
        
        if processing_text and len(processing_text) > 3:  # Минимальная длина для описания
            logger.info(f"Обработка текстового описания без фото: '{processing_text}' (Date: {custom_date or 'Today'})")
            
            # Импортируем обработчик описания из photo.py
            from handlers.photo import handle_description
            from services.state import UserState
            
            # Создаём состояние для обработки
            new_user_state = UserState(
                user_id=user_id,
                state='waiting_description',
                data={
                    'photo_paths': [],
                    'photo_file_ids': [],
                    'caption': '',  # Не дублируем текст в caption
                    'date': custom_date,  # Сохраняем дату (может быть None)
                }
            )
            state_manager.set_state(user_id, new_user_state)
            
            # Отправляем сообщение о начале анализа
            msg_text = "🤖 Анализирую через ИИ: еда, время, вес, КБЖУ... ⏳"
            if custom_date:
                msg_text += f"\n📅 Дата записи: {custom_date}"
            
            processing_msg = await message.answer(msg_text)
            
            # Обрабатываем описание (передаем очищенный текст)
            await handle_description(message, processing_text, processing_message=processing_msg, custom_date=custom_date)





@router.message(F.video_note)
async def handle_video_note(message: Message, state: FSMContext):
    """Обработчик видеосообщений"""
    await message.answer("📹 Видеосообщения пока не поддерживаются. Отправь фото или текстовое описание.")
