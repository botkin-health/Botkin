# Архитектура проекта HealthVault

## 1. Точка входа и склейка модулей
- **`telegram-bot/bot.py`**
  - Загружает переменные окружения (`dotenv` + `.env` в корне).
  - Настраивает логирование в `logs/bot.log`.
  - Создает `Dispatcher` (aiogram), подключает middleware и routers.

## 2. Middleware
- **`telegram-bot/middlewares/auth.py`**
  - Whitelist-доступ: проверка через `config/users.py`.
  - Прокидывает `user_id`, `username`, `first_name` в handler data.
- **`telegram-bot/middlewares/idempotency.py`**
  - Дедупликация апдейтов (защита от повторной доставки сообщений Telegram).

## 3. Роутеры (Handlers)
- **`telegram-bot/handlers/commands.py`**
  - Команды `/start`, `/help`, `/day`, `/week`, `/vitamins` и др.
  - Команда `/day` использует `services/nutrition_service.py` и подтягивает данные из Garmin (через `core/garmin_data.py`).
- **`telegram-bot/handlers/photo.py`**
  - Сохраняет фото в `data/media/...`.
  - Сначала пытается распознать скриншоты весов (`core/ocr_weight.py`).
  - Затем распознает меню/еду из фото (`core/menu_parser.py`).
  - Если не хватает данных — запрашивает текстовое описание и ведет диалог через `services/state.py`.
- **`telegram-bot/handlers/text.py`**
  - Если бот ждет описание после фото — делегирует обработку обратно в `handlers/photo.py` (`handle_description`).
  - В противном случае запускает LLM-классификацию (`core/llm_router.analyze_message`).

## 4. Машина состояний (State Machine)
- **`services/state.py`** — простой in-memory `state_manager`.
- *Нюанс:* При пересоздании `UserState` легко потерять поля (например, `menu_data`). Подробнее в `docs/architecture/STATE_MANAGEMENT.md`.

## 5. LLM Пайплайн (Классификация и Парсинг)
- **`core/llm_router.py`**
  - Формирует system prompt.
  - Вызывает OpenAI/Gemini/Claude (через HTTP/API-клиент).
  - Ожидает ответ строго в формате JSON.
- **`core/llm_food_processor.py`**
  - Переводит JSON от router во внутренний формат `meal_items` / `meal_totals`.
  - Приоритетно сверяет данные с локальной продуктовой базой (`core/product_search.py`) и regex-парсером описаний.

## 6. Данные и Персистентность (PostgreSQL)
Основной актуальный слой работы с БД построен на SQLAlchemy:
- **`database/models.py`** — модели (users, nutrition_log, weights, supplements_log, activity_log, blood_tests).
- **`database/crud.py`** — Основные CRUD-операции и агрегации.
- **`database/__init__.py`** — инициализация `engine`, `SessionLocal`.

*Запись из бота:*
- **`helpers/db_save.py`** — преобразует данные из state/handlers и пишет их через `database.crud`.

*Чтение для интерфейса:*
- **`services/nutrition_service.py`** — собирает дневную статистику (потребленное / цели / остаток).

*Примечание:* Есть наследуемый слой `database/repository.py` на `psycopg2` (таблицы `*_logs`, `nutrition_entries`). Перед изменениями всегда проверяйте, какой слой используется в целевом участке кода.
