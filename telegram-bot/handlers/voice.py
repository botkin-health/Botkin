import logging
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from core.infra.voice_service import voice_service

router = Router()

logger = logging.getLogger(__name__)


@router.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot, user_id: int, state: FSMContext = None):
    """
    Обработчик голосовых сообщений: скачивает, транскрибирует и отдаёт текст
    в единый вход handle_text_message.
    """
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")

        file_id = message.voice.file_id
        file_info = await bot.get_file(file_id)
        file_path = file_info.file_path

        save_dir = Path("data/media/voice")
        save_dir.mkdir(parents=True, exist_ok=True)

        local_filename = f"{message.voice.file_unique_id}.ogg"
        local_path = save_dir / local_filename

        await bot.download_file(file_path, local_path)

        text = await voice_service.transcribe(local_path)

        await message.reply(f"🎤 <b>Распознано:</b>\n\n{text}", parse_mode="HTML")

        text_stripped = text.strip()
        if not text_stripped:
            return

        # Тот же вход, что у текста: regex АД, режим диалога, даты, роутер.
        # Голос раньше шёл прямо в handle_description и вёл себя иначе, чем текст.
        from handlers.text import handle_text_message

        await handle_text_message(message, message.from_user.id, state, text_override=text_stripped)

    except Exception as e:
        logger.exception(f"Error handling voice message: {e}")
        await message.reply(f"❌ Произошла ошибка при обработке голоса: {e}")
