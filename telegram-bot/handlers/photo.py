#!/usr/bin/env python3
"""
Обработчик фото для бота с поддержкой нескольких фото и извлечения весов
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from pathlib import Path
import os
import asyncio

from services.state import state_manager, UserState
from services.storage import add_meal, get_today_totals
from services.nutrition import process_meal_description
from services.menu_parser import parse_menu_photo

router = Router()


# Callback data для кнопок подтверждения
class MealConfirmationCallback(CallbackData, prefix="meal"):
    action: str  # "save" или "cancel"
    meal_type: str = "default"  # "menu" или "regular"

# Блокировки и задачи для синхронизации обработки media group
# Ключ: (user_id, media_group_id), Значение: asyncio.Lock / asyncio.Task
_media_group_locks = {}
_media_group_tasks = {}


async def process_image_message(message: Message, photo_path: Path, photo_file_id: str = None):
    """
    Общая функция для обработки изображений (как photo, так и document)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = str(message.from_user.id)
    user_state = state_manager.get_state(user_id)
    
    # Если file_id не передан, получаем из document
    if not photo_file_id and message.document:
        photo_file_id = message.document.file_id
    
    # Проверяем, есть ли медиа-группа (несколько фото)
    media_group_id = message.media_group_id
    
    if media_group_id:
        # Используем блокировку для синхронизации доступа к состоянию
        lock_key = (user_id, media_group_id)
        
        # Получаем или создаём блокировку для этой группы
        if lock_key not in _media_group_locks:
            _media_group_locks[lock_key] = asyncio.Lock()
        
        lock = _media_group_locks[lock_key]
        
        async with lock:
            # Обновляем состояние после получения блокировки
            user_state = state_manager.get_state(user_id)
            is_new_group = user_state is None or user_state.data.get('media_group_id') != media_group_id
            
            if is_new_group:
                # Начинаем новую группу
                user_state = UserState(
                    user_id=user_id,
                    state='waiting_description',
                    data={
                        'media_group_id': media_group_id,
                        'photo_file_ids': [photo_file_id],
                        'photo_paths': [str(photo_path)],
                        'caption': message.caption or '',
                        'answered': False,
                    }
                )
                state_manager.set_state(user_id, user_state)
            else:
                # Добавляем фото к существующей группе
                # Проверяем дубликаты (иногда Telegram шлет дубли)
                if str(photo_path) not in user_state.data['photo_paths']:
                    user_state.data['photo_file_ids'].append(photo_file_id)
                    user_state.data['photo_paths'].append(str(photo_path))
                
                # Обновляем caption, если он пришел в этом сообщении
                if message.caption:
                    user_state.data['caption'] = message.caption
                state_manager.set_state(user_id, user_state)
        
        # Debounce: отменяем предыдущую задачу и запускаем новую
        task_key = (user_id, media_group_id)
        if task_key in _media_group_tasks:
            _media_group_tasks[task_key].cancel()
            
        # Запускаем отложенную обработку (ждем 2 секунды, чтобы собрать все фото)
        _media_group_tasks[task_key] = asyncio.create_task(
            process_media_group_delayed(message, media_group_id, user_id)
        )
            
    else:
        # Одно фото - обрабатываем сразу
        await process_photos_list(message, [photo_path], None)


async def process_media_group_delayed(message: Message, media_group_id: str, user_id: str):
    """Отложенная обработка группы фото"""
    try:
        await asyncio.sleep(2.0)  # Ждем загрузки всех фото
        
        # Удаляем задачу из списка
        task_key = (user_id, media_group_id)
        if task_key in _media_group_tasks:
            del _media_group_tasks[task_key]
            
        # Получаем актуальное состояние
        user_state = state_manager.get_state(user_id)
        if not user_state or user_state.data.get('media_group_id') != media_group_id:
            return
            
        if user_state.data.get('answered', False):
            return
            
        # Получаем все пути к фото
        photo_paths = [Path(p) for p in user_state.data.get('photo_paths', [])]
        
        if not photo_paths:
            return
            
        # Обрабатываем список фото
        await process_photos_list(message, photo_paths, media_group_id)
        
    except asyncio.CancelledError:
        # Задача была отменена (пришло новое фото), это нормально
        pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Ошибка в process_media_group_delayed: {e}")


from typing import List

async def process_photos_list(message: Message, photo_paths: List[Path], media_group_id: str = None):
    """Обрабатывает список фото (одиночное или группа)"""
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = str(message.from_user.id)
    
    # Если это медиа-группа, проверяем, не ответили ли уже
    if media_group_id:
        user_state = state_manager.get_state(user_id)
        if user_state and user_state.data.get('answered', False):
            return
        
        # Отмечаем, что ответили
        if user_state:
            user_state.data['answered'] = True
            state_manager.set_state(user_id, user_state)
            
            # Актуализируем caption из состояния, если в текущем сообщении его нет
            if not message.caption and user_state.data.get('caption'):
                # Создаем копию сообщения с caption из состояния (для обработки)
                # Note: message.caption is immutable usually, we just use local var
                pass

    photo_count = len(photo_paths)
    await message.answer(f"📸 Получено {photo_count} фото! Анализирую через ИИ: еда, меню, весы, КБЖУ...")
    
    # Получаем API ключ для OCR
    try:
        from services.api_key_loader import get_google_vision_api_key
        api_key = get_google_vision_api_key()
    except ImportError:
        api_key = os.getenv('GOOGLE_VISION_API_KEY')
    
    # Передаем весь список фото в парсер
    menu_data = parse_menu_photo(photo_paths, api_key)
    
    # Логируем результат распознавания меню
    if menu_data:
        logger.info(f"Распознано меню/еда: {menu_data.get('dish_name')}, КБЖУ: {menu_data.get('calories')} ккал")
        
        # --- ЛОГИКА ДОБАВОК ---
        if menu_data.get('is_supplement'):
            dish_name = menu_data.get('dish_name', '')
            logger.info(f"💊 Распознаны добавки по фото: {dish_name}")
            
            from services.supplement_service import supplement_service
            logged_items, remaining_items = supplement_service.log_intake(dish_name)
            
            response = f"💊 <b>По фото распознано:</b> {dish_name}\n"
            if logged_items:
                response += f"✅ <b>Записано в журнал:</b> {', '.join(logged_items)}\n\n"
            else:
                response += "⚠️ <b>Не удалось сопоставить с вашим планом.</b> Проверьте названия.\n\n"
                
            if remaining_items:
                response += "⏳ <b>Осталось принять сегодня:</b>\n" + "\n".join(remaining_items)
            else:
                response += "🎉 <b>На сегодня все витамины приняты!</b>"
            
            await message.answer(response)
            return
        # ----------------------
        
    else:
        logger.info("Меню/еда не распознано")
    
    if menu_data and menu_data.get('calories', 0) > 0:
        # Это меню или еда с распознанными КБЖУ
        logger.info(f"Распознано: {menu_data.get('dish_name')}")
        
        # Получаем caption из состояния или сообщения
        user_state = state_manager.get_state(user_id)
        caption = message.caption
        if user_state and user_state.data.get('caption'):
            caption = user_state.data.get('caption')
        
        # Если есть caption - обрабатываем его как описание с учетом данных меню
        if caption:
            logger.info(f"Есть caption, обрабатываем с учетом распознанного: {caption}")
            
            if not user_state:
                user_state = UserState(
                    user_id=user_id,
                    state='waiting_description',
                    data={
                        'photo_paths': [str(p) for p in photo_paths],
                        'photo_file_ids': [message.photo[-1].file_id if message.photo else ''],
                        'caption': caption,
                        'menu_data': menu_data,
                    }
                )
            else:
                user_state.data['menu_data'] = menu_data
                # Убедимся, что caption актуальный
                user_state.data['caption'] = caption
            state_manager.set_state(user_id, user_state)
            
            # Обрабатываем описание с учетом меню
            await handle_description(message, caption)
        else:
            # Нет caption - используем данные как есть
            logger.info(f"Используем данные без caption: {menu_data.get('dish_name')}")
            # Для handle_menu_photo передаем первое фото как "основное" для отображения
            await handle_menu_photo(message, menu_data, photo_paths[0])
    else:
        # Не меню/еда (или не удалось распознать КБЖУ) - просим описание
        
        # Получаем caption
        user_state = state_manager.get_state(user_id)
        caption = message.caption
        if user_state and user_state.data.get('caption'):
            caption = user_state.data.get('caption')

        if caption:
            # Если есть caption - обрабатываем сразу
            logger.info(f"Обрабатываем описание: {caption}")
            await handle_description(message, caption)
        else:
            # Не меню и нет caption - устанавливаем состояние и просим описание
            # Если состояния нет (одиночное фото без группы)
            if not user_state:
                 user_state = UserState(
                    user_id=user_id,
                    state='waiting_description',
                    data={
                        'photo_paths': [str(p) for p in photo_paths],
                        'photo_file_ids': [message.photo[-1].file_id if message.photo else ''],
                        'caption': '',
                    }
                )
                 state_manager.set_state(user_id, user_state)
            
            await message.answer(
                f"📸 Получено {photo_count} фото!\n"
                "Отправь описание:\n"
                "• Название блюда или продукта\n"
                "• Компоненты с весами\n"
                "• Или просто название - бот попробует распознать меню или найти продукт"
            )


@router.message(F.photo)
async def handle_photo(message: Message):
    """Обработка фото с описанием блюда"""
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"📸 Получено фото от пользователя {message.from_user.id}")
    
    # Получаем фото
    photo = message.photo[-1]  # Берем фото наибольшего размера
    photo_file_id = photo.file_id
    
    # Сохраняем фото
    photo_path = await save_photo(message, photo_file_id)
    
    if not photo_path:
        await message.answer("❌ Ошибка при сохранении фото")
        return
    
    # Обрабатываем изображение
    await process_image_message(message, photo_path, photo_file_id)


@router.message(F.document)
async def handle_document_image(message: Message):
    """Обработка документов с изображениями (например, при перетаскивании из приложения 'Фото' macOS)"""
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Проверяем, является ли документ изображением
    if not message.document:
        return
    
    # Проверяем MIME-тип или расширение файла
    mime_type = message.document.mime_type or ''
    file_name = message.document.file_name or ''
    
    # Список поддерживаемых типов изображений
    image_mime_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/heic', 'image/heif']
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif']
    
    is_image = (
        mime_type.lower() in image_mime_types or
        any(file_name.lower().endswith(ext) for ext in image_extensions)
    )
    
    if not is_image:
        # Это не изображение - пропускаем
        return
    
    logger.info(f"📸 Получен документ-изображение от пользователя {message.from_user.id}: {file_name} ({mime_type})")
    
    # Сохраняем документ как изображение
    photo_file_id = message.document.file_id
    photo_path = await save_document_as_image(message, photo_file_id, file_name)
    
    if not photo_path:
        await message.answer("❌ Ошибка при сохранении изображения")
        return
    
    # Обрабатываем изображение так же, как обычное фото
    await process_image_message(message, photo_path, photo_file_id)


async def save_photo(message: Message, file_id: str) -> Path:
    """Сохраняет фото на диск"""
    try:
        # Получаем файл
        file = await message.bot.get_file(file_id)
        
        # Создаем директорию для медиа
        date_str = datetime.now().strftime('%Y-%m-%d')
        media_dir = Path(__file__).parent.parent.parent / 'data' / 'media' / 'nutrition' / date_str
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем фото
        photo_path = media_dir / f"{file_id}.jpg"
        await message.bot.download_file(file.file_path, photo_path)
        
        return photo_path
    except Exception as e:
        print(f"Ошибка при сохранении фото: {e}")
        return None


async def save_photo(message: Message, file_id: str) -> Path:
    """Сохраняет фото на диск"""
    try:
        # Получаем файл
        file = await message.bot.get_file(file_id)
        
        # Создаем директорию для медиа
        date_str = datetime.now().strftime('%Y-%m-%d')
        media_dir = Path(__file__).parent.parent.parent / 'data' / 'media' / 'nutrition' / date_str
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем фото
        photo_path = media_dir / f"{file_id}.jpg"
        await message.bot.download_file(file.file_path, photo_path)
        
        return photo_path
    except Exception as e:
        print(f"Ошибка при сохранении фото: {e}")
        return None


async def save_document_as_image(message: Message, file_id: str, file_name: str = None) -> Path:
    """Сохраняет документ-изображение на диск"""
    try:
        # Получаем файл
        file = await message.bot.get_file(file_id)
        
        # Создаем директорию для медиа
        date_str = datetime.now().strftime('%Y-%m-%d')
        media_dir = Path(__file__).parent.parent.parent / 'data' / 'media' / 'nutrition' / date_str
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # Определяем расширение файла
        if file_name:
            ext = Path(file_name).suffix.lower()
            if not ext or ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif']:
                ext = '.jpg'  # По умолчанию jpg
        else:
            ext = '.jpg'
        
        # Сохраняем документ как изображение
        photo_path = media_dir / f"{file_id}{ext}"
        await message.bot.download_file(file.file_path, photo_path)
        
        return photo_path
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при сохранении документа-изображения: {e}")
        return None


# УБРАНО: обработчик текста перенесен в handlers/text.py
# Это нужно, чтобы текстовые сообщения без фото обрабатывались правильно


async def handle_description(message: Message, description: str = None, processing_message: Message = None):
    """
    Обработка описания блюда после получения фото.
    
    Args:
        message: Исходное сообщение
        description: Текст описания
        processing_message: Сообщение "Анализирую...", которое нужно отредактировать (опционально)
    """
    
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = str(message.from_user.id)
    user_state = state_manager.get_state(user_id)
    
    if not user_state or user_state.state != 'waiting_description':
        return
    
    # Если description не передан, берем из сообщения
    if description is None:
        description = message.text.strip() if message.text else ''
    
    if not description:
        await message.answer("Пожалуйста, отправь описание блюда")
        return
    
    # Получаем данные о фото
    photo_paths = user_state.data.get('photo_paths', [])
    caption = user_state.data.get('caption', '')
    menu_data = user_state.data.get('menu_data')  # Данные меню, если есть
    
    # Объединяем caption и description
    full_description = f"{caption}\n{description}".strip() if caption else description
    
    # Определяем множитель порции из описания
    portion_multiplier = 1.0
    import re
    # Поиск дробей вида "1/2", "1/3", "2/3", "3/4" и т.д.
    fraction_match = re.search(r'\b(\d+)/(\d+)\b', description)
    # Поиск десятичных чисел вида "0.5", "0,5"
    decimal_match = re.search(r'\b(0[.,]\d+)\b', description)
    
    if fraction_match:
        try:
            numerator = int(fraction_match.group(1))
            denominator = int(fraction_match.group(2))
            if denominator != 0:
                portion_multiplier = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            pass
    elif decimal_match:
        try:
            portion_multiplier = float(decimal_match.group(1).replace(',', '.'))
        except ValueError:
            pass
    elif 'половину' in description.lower() or 'половина' in description.lower():
        portion_multiplier = 0.5
    elif 'треть' in description.lower():
        portion_multiplier = 1.0 / 3.0
    elif 'четверть' in description.lower():
        portion_multiplier = 0.25
    
    # Получаем API ключ для OCR используя единую функцию
    try:
        from services.api_key_loader import get_google_vision_api_key
        api_key = get_google_vision_api_key()
    except ImportError:
        # Fallback: старая логика
        api_key = os.getenv('GOOGLE_VISION_API_KEY')
        if not api_key:
            key_file = Path(__file__).parent.parent.parent / '.google_vision_api_key'
            if not key_file.exists():
                family_docs_key = Path.home() / "FamilyDocs" / ".google_vision_api_key"
                if family_docs_key.exists():
                    key_file = family_docs_key
            if key_file.exists():
                try:
                    api_key = key_file.read_text().strip()
                except Exception:
                    pass
    
    # Конвертируем пути в Path объекты
    photo_path_objects = [Path(p) for p in photo_paths] if photo_paths else None
    
    try:
        # Если есть данные меню, обрабатываем описание с учетом меню
        # Это позволяет пересчитать КБЖУ на указанный вес и добавить дополнительные продукты
        if menu_data:
            logger.info(f"Обработка описания с учетом меню: {full_description}")
            from services.nutrition import process_meal_description_with_menu
            meal_items, meal_totals = process_meal_description_with_menu(
                description=full_description,
                menu_data=menu_data,
                photo_paths=photo_path_objects,
                portion_multiplier=portion_multiplier,
                api_key=api_key
            )
        else:
            # Обычная обработка без меню
            meal_items, meal_totals = process_meal_description(
                description=full_description,
                photo_paths=photo_path_objects,
                portion_multiplier=portion_multiplier,
                api_key=api_key
            )
        
        if not meal_items:
            await message.answer(
                "❌ Не удалось распознать продукты в описании.\n"
                "Попробуй указать продукты более явно, например:\n"
                "'курица 200г, рис 150г, овощи 100г'"
            )
            return
        
        # Извлекаем название приёма пищи из описания
        from handlers.text import extract_meal_name
        meal_time = datetime.now().strftime('%H:%M')
        meal_name = extract_meal_name(full_description, meal_time)
        
        logger.info(f"Извлечено название приёма пищи: '{meal_name}' из описания: '{full_description[:50]}...'")
        
        # Обновляем состояние
        user_state.data.update({
            'description': full_description,
            'meal_items': meal_items,
            'meal_totals': meal_totals,
            'portion_multiplier': portion_multiplier,
            'meal_time': meal_time,
            'meal_name': meal_name,
        })
        
        logger.info(f"Сохранено в состояние: meal_name='{meal_name}', meal_time='{meal_time}'")
        user_state.state = 'waiting_confirmation'
        state_manager.set_state(user_id, user_state)
        
        # Формируем ответ
        response = format_meal_response(meal_items, meal_totals, portion_multiplier, meal_name)
        
        # Создаём inline keyboard с кнопками
        builder = InlineKeyboardBuilder()
        builder.button(
            text="✅ Сохранить",
            callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack()
        )
        builder.button(
            text="❌ Не сохранять",
            callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack()
        )
        builder.adjust(2)  # Две кнопки в ряд
        keyboard = builder.as_markup()
        
        if processing_message:
            # Если было сообщение о процессинге, редактируем его
            await processing_message.edit_text(response, parse_mode='HTML', reply_markup=keyboard)
        else:
            # Иначе отправляем новое
            await message.answer(response, parse_mode='HTML', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке описания: {e}", exc_info=True)
        await message.answer(
            f"❌ Ошибка при обработке описания: {str(e)}\n"
            "Попробуй еще раз или обратись к администратору."
        )


async def handle_menu_photo(message: Message, menu_data: dict, photo_path: Path):
    """Обработка распознанного меню кафе с КБЖУ"""
    
    user_id = str(message.from_user.id)
    
    dish_name = menu_data.get('dish_name', 'Блюдо из меню')
    calories = menu_data.get('calories', 0)
    protein = menu_data.get('protein', 0)
    fats = menu_data.get('fats', 0)
    carbs = menu_data.get('carbs', 0)
    
    # Формируем ответ
    response = (
        f"🍽️ <b>Распознано меню кафе!</b>\n\n"
        f"<b>{dish_name}</b>\n\n"
        f"📊 КБЖУ:\n"
        f"• Калории: {calories:.0f} ккал\n"
        f"• Белки: {protein:.1f} г\n"
        f"• Жиры: {fats:.1f} г\n"
        f"• Углеводы: {carbs:.1f} г"
    )
    
    # Создаём inline keyboard с кнопками
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Сохранить",
        callback_data=MealConfirmationCallback(action="save", meal_type="menu").pack()
    )
    builder.button(
        text="❌ Не сохранять",
        callback_data=MealConfirmationCallback(action="cancel", meal_type="menu").pack()
    )
    builder.adjust(2)  # Две кнопки в ряд
    keyboard = builder.as_markup()
    
    # Сохраняем данные в состояние для подтверждения
    user_state = UserState(
        user_id=user_id,
        state='waiting_confirmation',
        data={
            'dish_name': dish_name,
            'meal_items': [{
                'product': dish_name,
                'weight_g': None,
                'calories': calories,
                'protein': protein,
                'fats': fats,
                'carbs': carbs,
                'source': 'menu_ocr',
            }],
            'meal_totals': {
                'calories': calories,
                'protein': protein,
                'fats': fats,
                'carbs': carbs,
            },
            'photo_path': str(photo_path),
            'meal_time': datetime.now().strftime('%H:%M'),
            'menu_ocr': True,  # Флаг, что это меню
        }
    )
    state_manager.set_state(user_id, user_state)
    
    await message.answer(response, parse_mode='HTML', reply_markup=keyboard)


def format_meal_response(meal_items: list, meal_totals: dict, portion_multiplier: float, meal_name: str = None) -> str:
    """Форматирует ответ с информацией о блюде"""
    
    lines = []
    
    # Добавляем название приёма пищи, если указано
    if meal_name and meal_name != "Приём пищи":
        lines.append(f"🍽️ <b>{meal_name}</b>\n")
    
    # Добавляем информацию о каждом продукте
    for item in meal_items:
        product_name = item.get('product', 'Неизвестный продукт')
        weight = item.get('weight_g', 0)
        calories = item.get('calories', 0)
        protein = item.get('protein', 0)
        fats = item.get('fats', 0)
        carbs = item.get('carbs', 0)
        weight_source = item.get('weight_source', 'unknown')
        
        # Определяем источник веса для отображения
        source_icon = "📷" if weight_source == 'photo' else "📝" if weight_source == 'description' else "⚖️"
        
        lines.append(
            f"<b>{product_name}</b> ({weight}г) {source_icon}\n"
            f"{calories} ккал | {protein}г белка | {fats}г жиров | {carbs}г углеводов"
        )
    
    # Добавляем итоги
    lines.append("\n<b>Итого:</b>")
    lines.append(f"Калории: {meal_totals.get('calories', 0)} ккал")
    lines.append(f"Белки: {meal_totals.get('protein', 0)} г")
    lines.append(f"Жиры: {meal_totals.get('fats', 0)} г")
    lines.append(f"Углеводы: {meal_totals.get('carbs', 0)} г")
    
    # Добавляем информацию о точности
    has_estimated = any(item.get('weight_estimated', False) for item in meal_items)
    if has_estimated:
        lines.append("\n⚠️ Точность: средняя (±15-25%)")
    else:
        lines.append("\n✅ Точность: высокая (±5-10%)")
    
    if portion_multiplier != 1.0:
        lines.append(f"\n📊 Учтена порция: {int(portion_multiplier * 100)}%")
    
    # Убираем "✅ Сохранить?" - теперь это кнопки
    # lines.append("\n✅ Сохранить?")
    
    return "\n".join(lines)


# Импортируем logger
import logging

# Импортируем функцию сохранения
from handlers.text import save_meal_to_json, extract_meal_name


@router.callback_query(MealConfirmationCallback.filter())
async def handle_meal_confirmation(callback: CallbackQuery, callback_data: MealConfirmationCallback):
    """Обработчик нажатия на кнопки подтверждения сохранения блюда"""
    
    user_id = str(callback.from_user.id)
    user_state = state_manager.get_state(user_id)
    
    # Логируем
    logger = logging.getLogger(__name__)
    logger.info(f"Обработка callback: action={callback_data.action}, meal_type={callback_data.meal_type}, user_id={user_id}")
    
    if not user_state or user_state.state != 'waiting_confirmation':
        await callback.answer("⚠️ Состояние истекло. Отправьте фото заново.", show_alert=True)
        await callback.message.delete()
        return
    
    if callback_data.action == "save":
        # Сохраняем блюдо
        # Для меню используем dish_name, для обычных блюд - используем meal_name из состояния
        if callback_data.meal_type == "menu":
            meal_name = user_state.data.get('dish_name', 'Приём пищи')
        else:
            # Для обычных блюд (regular или description) используем meal_name из состояния
            meal_name = user_state.data.get('meal_name')
            if not meal_name or meal_name == "Приём пищи":
                # Если не найдено, пробуем извлечь из описания
                description = user_state.data.get('description', '')
                meal_time = user_state.data.get('meal_time', datetime.now().strftime('%H:%M'))
                from handlers.text import extract_meal_name
                meal_name = extract_meal_name(description, meal_time)
                logger.info(f"Извлечено название приёма пищи при сохранении: '{meal_name}' из '{description[:50]}...'")
            else:
                logger.info(f"Используется meal_name из состояния: '{meal_name}'")
        
        logger.info(f"Сохранение блюда: meal_name='{meal_name}', meal_type='{callback_data.meal_type}'")
        
        if save_meal_to_json(user_state.data, meal_name):
            await callback.answer("✅ Сохранено!", show_alert=False)
            await callback.message.edit_text(
                f"✅ <b>Сохранено!</b>\n\n"
                f"🍽️ <b>{meal_name}</b>\n"
                f"📊 КБЖУ:\n"
                f"• Калории: {user_state.data.get('meal_totals', {}).get('calories', 0):.0f} ккал\n"
                f"• Белки: {user_state.data.get('meal_totals', {}).get('protein', 0):.1f} г\n"
                f"• Жиры: {user_state.data.get('meal_totals', {}).get('fats', 0):.1f} г\n"
                f"• Углеводы: {user_state.data.get('meal_totals', {}).get('carbs', 0):.1f} г",
                parse_mode='HTML'
            )
        else:
            await callback.answer("❌ Ошибка при сохранении", show_alert=True)
            logger.error("Ошибка при сохранении в save_meal_to_json")
    else:
        # Не сохраняем
        await callback.answer("❌ Не сохранено", show_alert=False)
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ Не сохранено",
            parse_mode='HTML'
        )
    
    # Очищаем состояние
    state_manager.clear_state(user_id)

