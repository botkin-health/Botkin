#!/usr/bin/env python3
"""
Главный файл для запуска Botkin Telegram Bot.
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update, BotCommand, BotCommandScopeAllPrivateChats
from dotenv import load_dotenv
import os

from core._version import __version__

# Загружаем переменные окружения
load_dotenv(override=True)
load_dotenv(Path(__file__).parent.parent / ".env", override=True)


# Настраиваем логирование
class ConsoleFilter(logging.Filter):
    """Фильтр для консоли: только свои логи и ошибки"""

    def filter(self, record):
        # Пропускаем свои логи (main, handlers.*, services.*)
        if record.name == "__main__" or record.name.startswith(("handlers.", "services.")):
            return True
        # Пропускаем предупреждения и ошибки ото всех
        return record.levelno >= logging.WARNING


def setup_logging():
    # Создаем директорию для логов
    Path("logs").mkdir(exist_ok=True)

    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Очищаем существующие хендлеры
    root_logger.handlers.clear()

    # 1. Файловый хендлер — пишет ВСЁ (DEBUG и выше), ротация 5 МБ × 3 бэкапа = ~15 МБ макс
    file_handler = RotatingFileHandler("logs/bot.log", encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(file_handler)

    # 2. Консольный хендлер - только важное и красивое
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(ConsoleFilter())
    root_logger.addHandler(console_handler)

    # Заглушаем шумные библиотеки (чтобы они не захламляли даже файл слишком сильно, если там debug)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)  # Убираем спам о каждом апдейте


setup_logging()
logger = logging.getLogger(__name__)

# Создаем директорию для логов
Path("logs").mkdir(exist_ok=True)

# Получаем токен бота
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
    logger.error("Создайте файл .env и добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
    sys.exit(1)


# Инициализируем бота и диспетчер
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


def register_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков"""
    handlers_count = 0
    registered_modules = []
    errors = []

    # Register authorization middleware FIRST
    try:
        from middlewares.auth import AuthMiddleware

        dp.message.middleware(AuthMiddleware())
        logger.info("✅ Authorization middleware registered")
    except Exception as e:
        logger.error(f"❌ Failed to register auth middleware: {e}")
        errors.append(f"Auth middleware: {e}")

    try:
        from handlers.commands import router as commands_router

        dp.include_router(commands_router)
        count = len(commands_router.observers) if hasattr(commands_router, "observers") else 0
        handlers_count += count
        registered_modules.append("команд")
    except Exception as e:
        errors.append(f"Обработчик команд: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика команд: {e}")

    try:
        from handlers.photo import router as photo_router

        dp.include_router(photo_router)
        count = len(photo_router.observers) if hasattr(photo_router, "observers") else 0
        handlers_count += count
        registered_modules.append("фото")
    except Exception as e:
        errors.append(f"Обработчик фото: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика фото: {e}")

    try:
        from handlers.voice import router as voice_router

        dp.include_router(voice_router)
        count = len(voice_router.observers) if hasattr(voice_router, "observers") else 0
        handlers_count += count
        registered_modules.append("голоса")
    except Exception as e:
        errors.append(f"Обработчик голоса: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика голоса: {e}")

    try:
        from handlers.text import router as text_router

        dp.include_router(text_router)
        count = len(text_router.observers) if hasattr(text_router, "observers") else 0
        handlers_count += count
        registered_modules.append("текста")
    except Exception as e:
        errors.append(f"Обработчик текста: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика текста: {e}")

    try:
        from handlers.setup import router as setup_router

        dp.include_router(setup_router)
        count = len(setup_router.observers) if hasattr(setup_router, "observers") else 0
        handlers_count += count
        registered_modules.append("профиля")
    except Exception as e:
        errors.append(f"Обработчик профиля: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика профиля: {e}")

    try:
        from handlers.sync_cmd import router as sync_router

        dp.include_router(sync_router)
        count = len(sync_router.observers) if hasattr(sync_router, "observers") else 0
        handlers_count += count
        registered_modules.append("/sync")
    except Exception as e:
        errors.append(f"Обработчик /sync: {e}")
        logger.error(f"❌ Ошибка регистрации обработчика /sync: {e}")

    # Apple Health handlers removed
    pass

    if registered_modules:
        modules_str = ", ".join(registered_modules)
        logger.info(f"✅ Обработчики {modules_str} зарегистрированы: {handlers_count} обработчиков")

    # УБИРАЕМ универсальный обработчик текстовых сообщений - он мешает нормальной обработке
    # Вместо этого используем обработчик в handlers/text.py
    # Оставляем только обработчик для диагностики фото, которые не обработались

    # Middleware для обеспечения идемпотентности (дедупликация)
    try:
        from middlewares.idempotency import IdempotencyMiddleware

        dp.update.outer_middleware(IdempotencyMiddleware())
        logger.info("✅ IdempotencyMiddleware подключен")
    except ImportError as e:
        logger.error(f"❌ Не удалось подключить IdempotencyMiddleware: {e}")
        errors.append(f"Middleware: {e}")

    # Middleware для сборки медиагрупп
    try:
        from middlewares.media_group import MediaGroupMiddleware

        dp.message.middleware(MediaGroupMiddleware())
        logger.info("✅ MediaGroupMiddleware подключен")
    except Exception as e:
        logger.error(f"❌ Не удалось подключить MediaGroupMiddleware: {e}")
        errors.append(f"MediaGroupMiddleware: {e}")

    # Middleware для логирования всех апдейтов
    @dp.update.outer_middleware()
    async def log_update_middleware(handler, event, data):
        # event is the Update object here
        if isinstance(event, Update):
            log_msg = f"📥 Update {event.update_id}:"
            if event.message:
                log_msg += f" MSG id={event.message.message_id} date={event.message.date}"
            elif event.edited_message:
                log_msg += f" EDIT id={event.edited_message.message_id} date={event.edited_message.edit_date}"
            elif event.callback_query:
                log_msg += f" CB id={event.callback_query.id} data={event.callback_query.data}"
            else:
                log_msg += " (other type)"
            logger.info(log_msg)
        return await handler(event, data)

    # Добавляем обработчик для всех обновлений (для диагностики необработанных)
    # catch_all_updates удален чтобы исключить побочные эффекты

    # Проверяем наличие необходимых директорий
    try:
        Path("data/media/nutrition").mkdir(parents=True, exist_ok=True)
        Path("logs/nutrition").mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Создание директорий: {e}")

    # Если были ошибки - выводим тревожное сообщение
    if errors:
        error_msg = "❌ ⚠️ 🚨 Botkin НЕ ЗАПУЩЕН!\n\n"
        error_msg += "Ошибки при инициализации:\n"
        for i, error in enumerate(errors, 1):
            error_msg += f"{i}. {error}\n"
        error_msg += "\n⚠️ Перешли это сообщение разработчику для разбора логов!"
        logger.error(error_msg)
        print(error_msg)
        raise Exception("Ошибки при инициализации бота")

    # Если всё хорошо - одна строка успеха
    print("\n" + "=" * 50)
    print(f"🚀  Botkin v{__version__}")
    print("✅  Бот успешно запущен и готов к работе")
    print("📝  Логи пишутся в файл: logs/bot.log")
    print("=" * 50 + "\n")

    # Запускаем бота


async def main():
    """Главная функция запуска бота"""

    errors = []

    # Register handlers and middleware
    register_handlers(dp)

    # Set bot commands in menu
    commands = [
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="day", description="Итоги дня"),
        BotCommand(command="week", description="Анализ недели"),
        BotCommand(command="vitamins", description="Чек-лист витаминов"),
        BotCommand(command="share", description="Поделиться дашбордом здоровья"),
        BotCommand(command="profile", description="Настроить профиль (рост, возраст, цель)"),
        BotCommand(command="sync", description="Подтянуть свежие данные (Garmin, весы, погода)"),
        BotCommand(command="help", description="Помощь"),
    ]

    # Register dispatcher in the webhook server (for /telegram/webhook endpoint)
    try:
        from webhook.apple_health import set_telegram_dispatcher, start_webhook_server

        set_telegram_dispatcher(bot, dp)
        webhook_enabled = True
        logger.info("✅ Telegram dispatcher registered in webhook server")
    except ImportError:
        webhook_enabled = False
        logger.warning("⚠️ Apple Health webhook не загружен (webhook/apple_health.py не найден)")

    try:
        # We only set bot commands here.
        await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("✅ Команды бота установлены")
    except Exception as e:
        logger.error(f"❌ Не удалось установить команды: {e}")

    # Регистрируем webhook у Telegram. Идемпотентно: ставим только если
    # текущий URL отличается. Без этого после смены TELEGRAM_BOT_TOKEN
    # (или первого деплоя) Telegram не знает куда слать апдейты — сообщения
    # копятся в очереди и бот «молчит». Прецедент: 12.05.2026 при свитче
    # @HealthVault_bot → @Botkin_md_bot webhook не зарегистрировали вручную.
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "https://health.orangegate.cc/telegram/webhook")
    if webhook_enabled and webhook_url:
        try:
            info = await bot.get_webhook_info()
            if info.url != webhook_url:
                await bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
                logger.info(f"✅ Webhook зарегистрирован: {webhook_url}")
            else:
                logger.info(f"✅ Webhook уже актуален: {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Не удалось установить webhook: {e}")

    # Start FastAPI server (serves /telegram/webhook + /apple_health + /webapp).
    # No polling — Telegram updates arrive via webhook.
    try:
        if webhook_enabled:
            logger.info("🌐 Запуск webhook-сервера на порту 8081...")
            await start_webhook_server()
        else:
            # Fallback: polling if FastAPI server not available
            logger.warning("⚠️ Webhook-сервер не доступен, запускаем polling...")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        error_msg = "❌ ⚠️ 🚨 Botkin НЕ ЗАПУЩЕН!\n\n"
        error_msg += f"Ошибка при запуске: {e}\n"
        error_msg += "\n⚠️ Перешли это сообщение разработчику для разбора логов!"
        logger.error(error_msg, exc_info=True)
        print(error_msg)
        raise
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
