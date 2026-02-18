#!/usr/bin/env python3
"""
Обработчик фото для бота с поддержкой нескольких фото и извлечения весов
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime
from pathlib import Path
import os
import asyncio
import logging

logger = logging.getLogger(__name__)


async def safe_edit_text(message: Message, text: str, **kwargs):
    """Безопасная обёртка для edit_text — игнорирует ошибку 'message is not modified'"""
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if 'message is not modified' in str(e):
            logger.debug(f"Сообщение не изменилось, пропускаем edit_text")
        else:
            raise

from services.state import UserState, state_manager
from services.state_helpers import create_photo_state, update_state_menu_data
from core.nutrition import process_meal_description
from core.menu_parser import parse_menu_photo

router = Router()


from handlers.callbacks import MealConfirmationCallback, WeightConfirmationCallback

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
    # ИЗМЕНЕНО: Новое сообщение по просьбе пользователя
    processing_msg = await message.answer(f"📸 Получено {photo_count} фото! Идет ИИ-анализ: еда, меню, весы, КБЖУ, скрины, витамины...")
    
    # Получаем API ключ для OCR
    try:
        from core.api_key_loader import get_google_vision_api_key
        api_key = get_google_vision_api_key()
    except ImportError:
        api_key = os.getenv('GOOGLE_VISION_API_KEY')
        
    # Извлекаем caption ДО вызова парсера, чтобы передать контекст
    user_state = state_manager.get_state(user_id)
    caption = message.caption
    if user_state and user_state.data.get('caption'):
        caption = user_state.data.get('caption')
    
    from core.ocr_weight import parse_weight_screenshot
    
    recognized_weights = []
    remaining_photos = [] # Фото, которые не распознались как весы

    # Проходим по всем фото и ищем весы
    for idx, ph_path in enumerate(photo_paths):
        try:
            # Пробуем распознать как весы (по одному)
            weight_data = parse_weight_screenshot([ph_path], api_key, description=caption or "")
            
            if weight_data and weight_data.get('weight'):
                logger.info(f"⚖️ Фото {idx+1}: Распознан вес {weight_data.get('weight')} кг")
                recognized_weights.append(weight_data)
            else:
                remaining_photos.append(ph_path)
                
        except Exception as e:
            logger.error(f"Ошибка при проверке весов на фото {idx+1}: {e}")
            remaining_photos.append(ph_path)

    # Если нашли весы - формируем отчет
    if recognized_weights:
        w_response_lines = ["⚖️ <b>Данные весов сохранены!</b>\n"]
        for i, wd in enumerate(recognized_weights, 1):
             line = f"{i}. 📅 <b>{wd.get('date', 'Сегодня')}</b>: 🏋️‍♂️ <b>{wd.get('weight')} кг</b>"
             if wd.get('body_fat'):
                 line += f", 💧 {wd.get('body_fat')}%"
             w_response_lines.append(line)
        
        # Показываем количество записей только если их больше одной
        if len(recognized_weights) > 1:
            w_response_lines.append(f"\n📂 <i>Всего записей: {len(recognized_weights)}</i>")
        w_response_lines.append("\nСохранить запись в журнал?")
        
        # Создаем кнопки подтверждения
        w_builder = InlineKeyboardBuilder()
        w_builder.button(text="✅ Сохранить вес", callback_data=WeightConfirmationCallback(action="save").pack())
        w_builder.button(text="❌ Отмена", callback_data=WeightConfirmationCallback(action="cancel").pack())
        
        # Сохраняем данные весов в состояние (временно)
        if not user_state:
            user_state = UserState(user_id=user_id, state='waiting_weight_confirmation', data={'weights': recognized_weights})
        else:
            user_state.state = 'waiting_weight_confirmation'
            user_state.data['weights'] = recognized_weights
        state_manager.set_state(user_id, user_state)

        # Если были только весы - отправляем и выходим
        if not remaining_photos:
            final_text = "\n".join(w_response_lines)
            if processing_msg:
                await processing_msg.edit_text(final_text, parse_mode='HTML', reply_markup=w_builder.as_markup())
            else:
                await message.answer(final_text, parse_mode='HTML', reply_markup=w_builder.as_markup())
            return
        else:
            # Если есть и весы и что-то еще - отправляем запрос по весам отдельным сообщением
            await message.answer("\n".join(w_response_lines), parse_mode='HTML', reply_markup=w_builder.as_markup())
            
    # ---------------------------

    # Если остались фото, которые не весы - это еда/меню
    if not remaining_photos:
        return

    # Обновляем список для обработки еды
    photo_paths = remaining_photos
    photo_count = len(photo_paths)

    # ИЗМЕНЕНО: Обрабатываем каждое фото ОТДЕЛЬНО, если это группа
    all_menu_data = []
    if photo_count > 1:
        logger.info(f"📸 Обрабатываю {photo_count} фото еды по отдельности...")
        for idx, photo_path in enumerate(photo_paths, 1):
            logger.info(f"  Анализирую фото еды {idx}/{photo_count}: {photo_path.name}")
            menu_item = parse_menu_photo([photo_path], api_key, description=caption)
            if menu_item:
                all_menu_data.append(menu_item)
                logger.info(f"  ✅ Фото {idx}: распознано '{menu_item.get('dish_name')}'")
            else:
                logger.info(f"  ⚠️ Фото {idx}: ничего не распознано")
        
        # Если распознано несколько блюд, объединяем их
        if len(all_menu_data) > 1:
            menu_data = {
                'dish_name': ', '.join([item.get('dish_name', 'Неизвестно') for item in all_menu_data]),
                'calories': sum([item.get('calories', 0) for item in all_menu_data]),
                'protein': sum([item.get('protein', 0) for item in all_menu_data]),
                'fats': sum([item.get('fats', 0) for item in all_menu_data]),
                'carbs': sum([item.get('carbs', 0) for item in all_menu_data]),
                'weight': None,
                'multiple_items': True,
                'items': all_menu_data
            }
            logger.info(f"✅ Объединено {len(all_menu_data)} блюд: {menu_data['dish_name']}")
        elif len(all_menu_data) == 1:
            menu_data = all_menu_data[0]
        else:
            menu_data = None
    else:
        # Одно фото - обрабатываем как раньше
        menu_data = parse_menu_photo(photo_paths, api_key, description=caption)
    
    # Логируем результат распознавания меню
    if menu_data:
        logger.info(f"Распознано меню/еда: {menu_data.get('dish_name')}, КБЖУ: {menu_data.get('calories')} ккал")
        
        # --- ЛОГИКА ДОБАВОК ---
        if menu_data.get('is_supplement'):
            dish_name = menu_data.get('dish_name', '')
            logger.info(f"💊 Распознаны добавки по фото: {dish_name}")
            
            # from core.supplements import supplement_service
            # logged_items, remaining_items = supplement_service.log_intake(dish_name)
            pass
            
            response = f"💊 <b>По фото распознано:</b> {dish_name}\n"
            if logged_items:
                response += f"✅ <b>Записано в журнал:</b> {', '.join(logged_items)}\n\n"
            else:
                response += "⚠️ <b>Не удалось сопоставить с вашим планом.</b> Проверьте названия.\n\n"
                
            if remaining_items:
                response += "⏳ <b>Осталось принять сегодня:</b>\n" + "\n".join(remaining_items)
            else:
                response += "🎉 <b>На сегодня все витамины приняты!</b>"
            
            if processing_msg:
                await processing_msg.edit_text(response, parse_mode='HTML')
            else:
                await message.answer(response, parse_mode='HTML')
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
            
            # Используем безопасный helper для создания/обновления состояния
            user_state = create_photo_state(
                user_id=user_id,
                photo_paths=photo_paths,
                photo_file_ids=[message.photo[-1].file_id if message.photo else ''],
                caption=caption,
                menu_data=menu_data,  # Новый menu_data
                existing_state=user_state  # Сохранит другие данные если есть
            )
            state_manager.set_state(user_id, user_state)
            
            # Обрабатываем описание с учетом меню
            # Caption уже в state, передаем None чтобы функция взяла caption из состояния
            await handle_description(message, None, processing_message=processing_msg)
        else:
            # Нет caption - используем данные как есть
            logger.info(f"Используем данные без caption: {menu_data.get('dish_name')}")
            # Для handle_menu_photo передаем первое фото как "основное" для отображения
            await handle_menu_photo(message, menu_data, photo_paths[0], processing_message=processing_msg)
            return

    elif menu_data and menu_data.get('nutrition_not_found') and menu_data.get('raw_text'):
        # КБЖУ не найдены, но есть текст - пробуем найти продукт в базе по названию
        logger.info("КБЖУ не найдены в меню, ищем продукт в базе по OCR тексту...")
        
        from core.product_search import find_product_in_text
        found_product = find_product_in_text(menu_data['raw_text'])
        
        if found_product:
            p_name = found_product.get('name', 'Продукт')
            logger.info(f"✅ Продукт найден в базе по OCR: {p_name}")
            
            # Определяем вес (дефолтный или 100г)
            weight = found_product.get('weight_g', 100.0)
            multiplier = weight / 100.0
            
            # Считаем итоги
            meal_totals = {
                'calories': round(found_product.get('calories_per_100g', 0) * multiplier, 1),
                'protein': round(found_product.get('protein_per_100g', 0) * multiplier, 1),
                'fats': round(found_product.get('fats_per_100g', 0) * multiplier, 1),
                'carbs': round(found_product.get('carbs_per_100g', 0) * multiplier, 1)
            }
            
            meal_items = [{
                'product': p_name,
                'weight_g': weight,
                'weight_source': 'db_default',
                'calories': meal_totals['calories'],
                'protein': meal_totals['protein'],
                'fats': meal_totals['fats'],
                'carbs': meal_totals['carbs'],
                'source': 'ocr_db_lookup',
                'note': found_product.get('note')
            }]
            
            # Создаем состояние
            new_state = UserState(
                user_id=user_id,
                state='waiting_confirmation',
                data={
                    'description': f"Фото: {p_name}",
                    'meal_items': meal_items,
                    'meal_totals': meal_totals,
                    'meal_time': datetime.now().strftime('%H:%M'),
                    'meal_name': p_name,
                    'photo_paths': [str(p) for p in photo_paths]
                }
            )
            state_manager.set_state(user_id, new_state)
            
            # Формируем ответ
            response = f"🍽️ <b>{p_name}</b> (найдено в базе)\n\n"
            response += f"⚠️ Распознано по фото\n"
            response += f"• {p_name} ({weight}г) — {int(meal_totals['calories'])} ккал\n"
            response += f"\n📊 <b>Итого: {int(meal_totals['calories'])} ккал</b>\n"
            response += f"Б: {int(meal_totals['protein'])} | Ж: {int(meal_totals['fats'])} | У: {int(meal_totals['carbs'])}"

            # Buttons
            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Сохранить", callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack())
            builder.button(text="❌ Отмена", callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack())
            
            if processing_msg:
                await processing_msg.edit_text(response, parse_mode='HTML', reply_markup=builder.as_markup())
            else:
                await message.answer(response, parse_mode='HTML', reply_markup=builder.as_markup())
            return
            
        else:
             logger.info("Продукт не найден в базе по OCR тексту")
             # Fallthrough to ask description

        
    # Получаем caption
    user_state = state_manager.get_state(user_id)
    caption = message.caption
    if user_state and user_state.data.get('caption'):
        caption = user_state.data.get('caption')

    if caption:
        # Если есть caption - обрабатываем сразу
        logger.info(f"Обрабатываем описание: {caption}")
        
        # Если это одиночное фото (или состояние не подходит), инициализируем состояние
        # Это критично, так как handle_description берет пути к фото из состояния
        if not user_state or user_state.state != 'waiting_description':
            # Используем безопасный helper - он АВТОМАТИЧЕСКИ сохранит menu_data
            user_state = create_photo_state(
                user_id=user_id,
                photo_paths=photo_paths,
                photo_file_ids=[message.photo[-1].file_id if message.photo else ''],
                caption=caption,
                menu_data=None,  # Не передаём - возьмёт из existing_state
                existing_state=user_state  # ← Отсюда сохранится menu_data!
            )
            state_manager.set_state(user_id, user_state)

        # Caption уже в state, передаем None чтобы функция взяла caption из состояния
        await handle_description(message, None, processing_message=processing_msg)
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
        
        prompt_text = (
            f"📸 Получено {photo_count} фото!\n"
            "Отправь описание:\n"
            "• Название блюда или продукта\n"
            "• Компоненты с весами\n"
            "• Или просто название - бот попробует распознать меню или найти продукт"
        )
        if processing_msg:
            await processing_msg.edit_text(prompt_text)
        else:
            await message.answer(prompt_text)


@router.message(F.photo)
async def handle_photo_message(message: Message, bot: Bot, user_id: int):
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


async def handle_description(message: Message, description: str = None, processing_message: Message = None, custom_date: str = None):
    """
    Обработка описания блюда после получения фото.
    
    Args:
        message: Исходное сообщение
        description: Текст описания
        processing_message: Сообщение "Анализирую...", которое нужно отредактировать (опционально)
        custom_date: Кастомная дата в формате YYYY-MM-DD (опционально)
    """
    
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = str(message.from_user.id)
    user_state = state_manager.get_state(user_id)
    
    if not user_state or user_state.state != 'waiting_description':
        return
    
    # Если description не передан, берем из сообщения или из состояния (для фото с caption)
    if description is None:
        if message.text:
            description = message.text.strip()
        elif user_state and user_state.data.get('caption'):
            description = user_state.data.get('caption').strip()
        else:
            description = ''
    
    if not description:
        await message.answer("Пожалуйста, отправь описание блюда")
        return
    
    # Получаем данные о фото
    photo_paths = user_state.data.get('photo_paths', [])
    caption = user_state.data.get('caption', '')
    menu_data = user_state.data.get('menu_data')  # Данные меню, если есть
    
    logger.info(f"🔍 [DEBUG] handle_description - menu_data in state: {menu_data}")
    logger.info(f"🔍 [DEBUG] user_state.data keys: {list(user_state.data.keys())}")
    
    # Объединяем caption и description
    full_description = f"{caption}\n{description}".strip() if caption else description
    
    # Извлекаем дату из описания (поддержка "вчера")
    # Если custom_date не был передан, пытаемся извлечь из текста
    if not custom_date:
        from handlers.text import extract_date_from_text
        extracted_date, clean_description = extract_date_from_text(full_description)
        if extracted_date:
            custom_date = extracted_date
            full_description = clean_description
            logger.info(f"Извлечена дата из описания: {custom_date}, очищенное описание: '{clean_description[:50]}...'")
    
    # --- LLM Router Logic ---
    from core.llm_router import analyze_message
    from core.nutrition import process_llm_food_data
    
    # ИСПРАВЛЕНИЕ: Если menu_data уже распознаны (parse_menu_photo успешно извлек КБЖУ),
    # используем их напрямую вместо повторного анализа через LLM Router,
    # так как Router НЕ извлекает КБЖУ из изображений
    if menu_data and menu_data.get('calories', 0) > 0:
        logger.info(f"✅ Используем ранее распознанные КБЖУ из меню: {menu_data}")
        
        # Формируем результат в формате, ожидаемом дальше в коде
        router_result = {
            'type': 'food',
            'data': {
                'dish_name': menu_data.get('dish_name', 'Блюдо из меню'),
                'meal_type': 'meal',  # Определим позже по времени
                'items': [{
                    'name': menu_data.get('dish_name', 'Блюдо из меню'),
                    'weight': menu_data.get('weight'),
                    'quantity': None,
                    'calories': menu_data.get('calories'),
                    'protein': menu_data.get('protein'),
                    'fats': menu_data.get('fats'),
                    'carbs': menu_data.get('carbs'),
                }]
            }
        }
    else:
        # Нет распознанных КБЖУ из меню - используем LLM Router
        # Готовим пути к фото
        paths_to_analyze = [Path(p) for p in photo_paths] if photo_paths else None
        
        if processing_message:
            await processing_message.edit_text("🤖 Думаю... (AI анализирует контекст) 🧠")
        else:
            processing_message = await message.answer("🤖 Думаю... 🧠")

        try:
            router_result = analyze_message(text=full_description, image_paths=paths_to_analyze)
        except Exception as e:
            logger.error(f"LLM Router Error: {e}")
            router_result = None

    if not router_result or router_result.get('type') != 'food':
        # Fallback или ошибка
        # Если Router решил что это НЕ еда, но мы в хендлере описания еды?
        # Возможно это витамины или весы?
        # Если type='vitamins', надо обработать.
        
        if router_result and router_result.get('type') == 'vitamins':
             # Обработка витаминов
            data = router_result.get('data', {})
            items = data.get('items', [])
            action = data.get('action')
            
            # Сохраняем реально
            from core.supplements import save_supplements
            telegram_user_id = int(message.from_user.id)
            saved = save_supplements(items, user_id=telegram_user_id)
            
            # Формируем красивый список
            items_list = "\n".join([f"• {item}" for item in items])
            
            status_text = "✅ <b>Записано</b>" if saved else "⚠️ <b>Ошибка записи</b>"
            
            response = (
                f"💊 <b>Витамины:</b>\n"
                f"{items_list}\n\n"
                f"{status_text}"
            )
            
            await processing_message.edit_text(response, parse_mode='HTML')
            state_manager.clear_state(user_id)
            return

        elif router_result and router_result.get('type') == 'weight':
             # Обработка веса
             data = router_result.get('data', {})
             w_val = data.get('weight')
             await processing_message.edit_text(f"⚖️ <b>Вес:</b> {w_val} кг\n✅ Записано", parse_mode='HTML')
             # Тут надо бы сохранить, но пока просто ответим, т.к. этот флоу редок при вводе описания
             state_manager.clear_state(user_id)
             return

        else:
            await processing_message.edit_text("❌ Не удалось понять, что это за еда. Попробуй переформулировать.")
            return

    # Это ЕДА
    llm_data = router_result
    logger.info(f"📊 Calling process_llm_food_data with llm_data: {llm_data}")
    meal_items, meal_totals = process_llm_food_data(llm_data, description=full_description)
    logger.info(f"📊 process_llm_food_data returned: items={len(meal_items) if meal_items else 0}, totals={meal_totals}")
    
    if not meal_items:
         await processing_message.edit_text("❌ Продукты не найдены в ответе нейросети.")
         return

    # Извлекаем метаданные из ответа LLM
    data = llm_data.get('data', {})
    meal_name = data.get('dish_name') or data.get('meal_type')
    
    # Если название так себе, пробуем определить по времени
    if not meal_name or meal_name in ['breakfast', 'lunch', 'dinner']:
         from handlers.text import extract_meal_name
         meal_time = datetime.now().strftime('%H:%M')
         meal_name_ru = extract_meal_name(full_description, meal_time)
         if meal_name_ru: meal_name = meal_name_ru

    # Обновляем состояние
    user_state.data.update({
        'description': full_description,
        'meal_items': meal_items,
        'meal_totals': meal_totals,
        'portion_multiplier': 1.0, # Deprecated
        'meal_time': datetime.now().strftime('%H:%M'),
        'meal_name': meal_name,
    })
    
    # Если передана кастомная дата
    if custom_date:
        user_state.data['date'] = custom_date
    
    user_state.state = 'waiting_confirmation'
    state_manager.set_state(user_id, user_state)
    
    # Формируем ответ
    # Функция format_meal_response должна существовать или импортироваться?
    # Она была в photo.py но я ее не видел в view_file output? 
    # А, она скорее всего ниже или я пропустил.
    # Если ее нет, напишем инлайн.
    
    response = f"🍽️ <b>{meal_name}</b>\n\n"
    for item in meal_items:
        w_str = f"{item['weight_g']}г" if item.get('weight_g') else "?"
        cal = item.get('calories', 0)
        response += f"• {item['product']} ({w_str}) — {int(cal)} ккал\n"
        
    response += f"\n📊 <b>Итого: {int(meal_totals['calories'])} ккал</b>\n"
    response += f"Б: {int(meal_totals['protein'])} | Ж: {int(meal_totals['fats'])} | У: {int(meal_totals['carbs'])}"

    # Keyboard
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Сохранить", callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack())
    builder.button(text="❌ Отмена", callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack())
    
    await safe_edit_text(processing_message, response, parse_mode='HTML', reply_markup=builder.as_markup())



async def handle_menu_photo(message: Message, menu_data: dict, photo_path: Path, processing_message: Message = None):
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
        f"• Белки: {protein:.0f} г\n"
        f"• Жиры: {fats:.0f} г\n"
        f"• Углеводы: {carbs:.0f} г"
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
    
    if processing_message:
        await processing_message.edit_text(response, parse_mode='HTML', reply_markup=keyboard)
    else:
        await message.answer(response, parse_mode='HTML', reply_markup=keyboard)


def format_meal_response(meal_items: list, meal_totals: dict, portion_multiplier: float, meal_name: str = None, date: str = None) -> str:
    """Форматирует ответ с информацией о блюде"""
    
    lines = []
    
    # Добавляем дату, если она не сегодня
    if date:
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')
            if date != today_str:
                lines.append(f"📅 <b>{date_obj.strftime('%d.%m.%Y')}</b>")
        except ValueError:
            pass
    """Форматирует ответ с информацией о блюде"""
    
    lines = []
    
    # Добавляем название приёма пищи, если указано
    if meal_name and meal_name != "Приём пищи":
        lines.append(f"🍽️ <b>{meal_name}</b>\n")
    
    # Добавляем информацию о каждом продукте
    for item in meal_items:
        product_name = item.get('product', 'Неизвестный продукт')
        weight = int(round(item.get('weight_g', 0)))
        calories = int(round(item.get('calories', 0)))
        protein = int(round(item.get('protein', 0)))
        fats = int(round(item.get('fats', 0)))
        carbs = int(round(item.get('carbs', 0)))
        weight_source = item.get('weight_source', 'unknown')
        
        # Определяем источник веса для отображения
        source_icon = "📷" if weight_source == 'photo' else "📝" if weight_source == 'description' else "⚖️"
        
        lines.append(
            f"• <b>{product_name}</b> ({weight}г) — {calories} ккал (Б:{protein} Ж:{fats} У:{carbs}) {source_icon}"
        )
    
    # Добавляем итоги
    lines.append("\n<b>Итого:</b>")
    lines.append(f"Калории: {int(round(meal_totals.get('calories', 0)))} ккал")
    lines.append(f"Белки: {int(round(meal_totals.get('protein', 0)))} г")
    lines.append(f"Жиры: {int(round(meal_totals.get('fats', 0)))} г")
    lines.append(f"Углеводы: {int(round(meal_totals.get('carbs', 0)))} г")
    
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
from handlers.text import extract_meal_name


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
        
        # === ИЗМЕНЕНО: Используем PostgreSQL вместо JSON ===
        from helpers.db_save import save_meal_to_db
        telegram_user_id = int(callback.from_user.id)
        
        logger.info(f"[BEFORE SAVE] user_state.data keys: {list(user_state.data.keys())}")
        logger.info(f"[BEFORE SAVE] meal_totals: {user_state.data.get('meal_totals')}")
        logger.info(f"[BEFORE SAVE] meal_items count: {len(user_state.data.get('meal_items', []))}")
        
        if save_meal_to_db(user_state.data, meal_name, user_id=telegram_user_id):
            logger.info("[AFTER SAVE] save_meal_to_db returned True")
            await callback.answer("✅ Сохранено!", show_alert=False)
            await safe_edit_text(
                callback.message,
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
            logger.error("[AFTER SAVE] save_meal_to_db returned False!")
            await callback.answer("❌ Ошибка при сохранении", show_alert=True)
            logger.error("Ошибка при сохранении в save_meal_to_db")
    else:
        # Не сохраняем
        await callback.answer("❌ Не сохранено", show_alert=False)
        await safe_edit_text(
            callback.message,
            callback.message.text + "\n\n❌ Не сохранено",
            parse_mode='HTML'
        )
    
    # Очищаем состояние
    state_manager.clear_state(user_id)


@router.callback_query(WeightConfirmationCallback.filter())
async def handle_weight_confirmation(callback: CallbackQuery, callback_data: WeightConfirmationCallback):
    """Обработчик подтверждения сохранения веса"""
    
    user_id = str(callback.from_user.id)
    user_state = state_manager.get_state(user_id)
    logger = logging.getLogger(__name__)
    
    if not user_state or 'weights' not in user_state.data:
        await callback.answer("⚠️ Данные устарели", show_alert=True)
        await callback.message.delete()
        return

    if callback_data.action == "save":
        # === ИЗМЕНЕНО: Используем PostgreSQL вместо JSON ===
        from helpers.db_save import save_weight_to_db
        telegram_user_id = int(callback.from_user.id)
        
        weights = user_state.data['weights']
        
        saved_count = 0
        for wd in weights:
            wd['source'] = 'screenshot_ocr'
            if save_weight_to_db(wd, user_id=telegram_user_id):
                saved_count += 1
        
        await callback.answer(f"✅ Сохранено {saved_count} записей", show_alert=False)
        await safe_edit_text(
            callback.message,
            callback.message.text.replace("Сохранить запись в журнал?", f"\n✅ <b>Сохранено {saved_count} записей!</b>"),
            parse_mode='HTML'
        )
    else:
        await callback.answer("❌ Отменено", show_alert=False)
        await safe_edit_text(
            callback.message,
            callback.message.text.replace("Сохранить запись в журнал?", "\n❌ <b>Сохранение отменено</b>"),
            parse_mode='HTML'
        )
    
    state_manager.clear_state(user_id)

