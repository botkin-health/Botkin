#!/usr/bin/env python3
"""
Главный файл для запуска HealthVault Telegram Bot
"""

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.filters import Command
from dotenv import load_dotenv
import os

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
class ConsoleFilter(logging.Filter):
    """Фильтр для консоли: только свои логи и ошибки"""
    def filter(self, record):
        # Пропускаем свои логи (main, handlers.*, services.*)
        if record.name == '__main__' or record.name.startswith(('handlers.', 'services.')):
            return True
        # Пропускаем предупреждения и ошибки ото всех
        return record.levelno >= logging.WARNING

def setup_logging():
    # Создаем директорию для логов
    Path('logs').mkdir(exist_ok=True)
    
    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Очищаем существующие хендлеры
    root_logger.handlers.clear()
    
    # 1. Файловый хендлер - пишет ВСЁ (DEBUG и выше)
    file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    root_logger.addHandler(file_handler)
    
    # 2. Консольный хендлер - только важное и красивое
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    console_handler.addFilter(ConsoleFilter())
    root_logger.addHandler(console_handler)
    
    # Заглушаем шумные библиотеки (чтобы они не захламляли даже файл слишком сильно, если там debug)
    logging.getLogger('httpcore').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.INFO)
    logging.getLogger('aiogram.event').setLevel(logging.WARNING) # Убираем спам о каждом апдейте

setup_logging()
logger = logging.getLogger(__name__)

# Создаем директорию для логов
Path('logs').mkdir(exist_ok=True)

# Получаем токен бота
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
    logger.error("Создайте файл .env и добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
    sys.exit(1)

# Инициализируем бота и диспетчер
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


async def main():
    """Главная функция запуска бота"""
    
    errors = []
    
    # Регистрируем обработчики
    # ВАЖНО: команды регистрируем ПЕРВЫМИ, чтобы они не перехватывались другими обработчиками
    handlers_count = 0
    registered_modules = []
    
    try:
        from handlers.commands import router as commands_router
        dp.include_router(commands_router)
        count = len(commands_router.observers) if hasattr(commands_router, 'observers') else 0
        handlers_count += count
        registered_modules.append("команд")
    except Exception as e:
        errors.append(f"Обработчик команд: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика команд: {e}")
    
    try:
        from handlers.photo import router as photo_router
        dp.include_router(photo_router)
        count = len(photo_router.observers) if hasattr(photo_router, 'observers') else 0
        handlers_count += count
        registered_modules.append("фото")
    except Exception as e:
        errors.append(f"Обработчик фото: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика фото: {e}")
    
    try:
        from handlers.text import router as text_router
        dp.include_router(text_router)
        count = len(text_router.observers) if hasattr(text_router, 'observers') else 0
        handlers_count += count
        registered_modules.append("текста")
    except Exception as e:
        errors.append(f"Обработчик текста: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика текста: {e}")
        
    if registered_modules:
        modules_str = ", ".join(registered_modules)
        logger.info(f"✅ Обработчики {modules_str} зарегистрированы: {handlers_count} обработчиков")
    
    # УБИРАЕМ универсальный обработчик текстовых сообщений - он мешает нормальной обработке
    # Вместо этого используем обработчик в handlers/text.py
    # Оставляем только обработчик для диагностики фото, которые не обработались
    
    # Добавляем обработчик для всех обновлений (для диагностики)
    @dp.update()
    async def catch_all_updates(update: Update):
        """Обработчик для всех обновлений (для диагностики)"""
        if update.message:
            # Если это сообщение, но оно не обработано - логируем детали
            msg = update.message
            if msg.photo:
                logger.error(f"❌ КРИТИЧНО: Обновление с фото не обработано! update_id={update.update_id}, message_id={msg.message_id}, photo_count={len(msg.photo)}")
                # Пытаемся обработать вручную
                try:
                    from handlers.photo import handle_photo
                    logger.info(f"🔄 Пытаюсь обработать фото из update вручную...")
                    await handle_photo(msg)
                except Exception as e:
                    logger.error(f"❌ Ошибка при ручной обработке фото из update: {e}")
                    import traceback
                    traceback.print_exc()
    
    # Проверяем наличие необходимых директорий
    try:
        Path('data/media/nutrition').mkdir(parents=True, exist_ok=True)
        Path('logs/nutrition').mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Создание директорий: {e}")
    
    # Если были ошибки - выводим тревожное сообщение
    if errors:
        error_msg = "❌ ⚠️ 🚨 HealthVault Tracker НЕ ЗАПУЩЕН!\n\n"
        error_msg += "Ошибки при инициализации:\n"
        for i, error in enumerate(errors, 1):
            error_msg += f"{i}. {error}\n"
        error_msg += "\n⚠️ Перешли это сообщение разработчику для разбора логов!"
        logger.error(error_msg)
        print(error_msg)
        raise Exception("Ошибки при инициализации бота")
    
    # Если всё хорошо - одна строка успеха
    print("\n" + "="*50)
    print("🚀  HealthVault Tracker v1.2")
    print("✅  Бот успешно запущен и готов к работе")
    print(f"📝  Логи пишутся в файл: logs/bot.log")
    print("="*50 + "\n")
    
    # Запускаем бота
    try:
        # Удаляем вебхук, если он был установлен
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        error_msg = f"❌ ⚠️ 🚨 HealthVault Tracker НЕ ЗАПУЩЕН!\n\n"
        error_msg += f"Ошибка при запуске: {e}\n"
        error_msg += "\n⚠️ Перешли это сообщение разработчику для разбора логов!"
        logger.error(error_msg, exc_info=True)
        print(error_msg)
        raise
    finally:
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)

