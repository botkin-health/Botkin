import os
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import Message
from core.voice_service import voice_service
from services.state import state_manager, UserState
from handlers.photo import handle_description

router = Router()

@router.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot):
    """
    Обработчик голосовых сообщений.
    Скачивает файл, транскрибирует и возвращает текст.
    """
    try:
        # Сообщаем пользователю, что "слышим" его
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Инфо о файле
        file_id = message.voice.file_id
        file_info = await bot.get_file(file_id)
        file_path = file_info.file_path
        
        # Путь для сохранения (в /tmp или в папку медиа)
        # Телеграм отдает .oga/.ogg, Whisper их понимает
        save_dir = Path("data/media/voice")
        save_dir.mkdir(parents=True, exist_ok=True)
        
        local_filename = f"{message.voice.file_unique_id}.ogg"
        local_path = save_dir / local_filename
        
        # Скачиваем
        await bot.download_file(file_path, local_path)
        
        # Транскрибируем
        text = await voice_service.transcribe(local_path)
        
        # Отвечаем
        await message.reply(f"🎤 <b>Распознано:</b>\n\n{text}")

        # --- Логика обработки добавок ---
        from core.supplements import supplement_service
        logged_items, remaining_items = supplement_service.log_intake(text)
        if logged_items:
             response = f"💊 <b>Сохранено:</b> {', '.join(logged_items)}\n\n"
             if remaining_items:
                 response += "⏳ <b>Осталось принять сегодня:</b>\n" + "\n".join(remaining_items)
             else:
                 response += "🎉 <b>На сегодня все витамины приняты!</b>"
            
             await message.answer(response)
             return
        # -----------------------------
        
        # --- Логика обработки еды ---
        # Если текст похож на описание еды (длиннее 3 символов), запускаем обработчик
        if len(text.strip()) > 3:
            user_id = str(message.from_user.id)
            
            # Создаём состояние
            new_user_state = UserState(
                user_id=user_id,
                state='waiting_description',
                data={
                    'photo_paths': [],
                    'photo_file_ids': [],
                    'caption': text,
                }
            )
            state_manager.set_state(user_id, new_user_state)
            
            # Сообщаем, что начали анализ
            processing_msg = await message.answer("🤖 Анализирую через ИИ: еда, время, вес, КБЖУ... ⏳")
            
            # Запускаем анализ (используем тот же механизм, что и для текста/фото)
            await handle_description(message, text, processing_message=processing_msg)
        # -----------------------------
        
        # Удаляем временный файл (опционально, пока оставим для дебага или удалим)
        # os.remove(local_path)
        
    except Exception as e:
        await message.reply(f"❌ Произошла ошибка при обработке голоса: {e}")
        # Логгирование ошибки должно быть в middleware или логгере бота, 
        # но здесь тоже можно принтнуть
        print(f"Error handling voice: {e}")
