# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

> В репозитории есть правило `.cursorrules`: **общаться по-русски** и **писать документы по-русски**. Этот файл (кроме обязательного англоязычного префикса выше) тоже ориентирован на русский.

## Что это за репозиторий (кратко)
HealthVault — персональная система учёта здоровья. Основной интерфейс — Telegram-бот (aiogram 3.x), который принимает текст/голос/фото и:
- классифицирует сообщение (еда / вес / витамины / прочее) через LLM,
- извлекает структуру (ингредиенты/вес/КБЖУ и т.п.),
- сохраняет данные в PostgreSQL,
- отдаёт агрегированную статистику командами `/day`, `/week`, `/vitamins`.

Код: Python. Продакшн — Docker + Postgres. Есть dev `docker-compose.dev.yml` для локальной БД.

## Частые команды (локальная разработка)

### 1) Виртуальное окружение и зависимости
Makefile ожидает venv в корне (`./venv`).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Альтернатива через make (после создания venv):
```bash
make install
```

### 2) Запуск бота локально
Запуск «с проверками» (остановит старый процесс, прогонит тесты и mypy, затем запустит):
```bash
make run
```

Быстрый запуск без тестов/типов:
```bash
make run-fast
```

Остановить локально запущенный бот:
```bash
make stop
```

Точка входа бота: `telegram-bot/bot.py`.

### 3) Тесты
Все тесты:
```bash
make test
```

Один тестовый файл:
```bash
PYTHONPATH=. ./venv/bin/python -m pytest tests/test_nutrition_logic.py
```

Один тест (nodeid):
```bash
PYTHONPATH=. ./venv/bin/python -m pytest tests/test_week_command.py::test_week_command
```

По имени (substring):
```bash
PYTHONPATH=. ./venv/bin/python -m pytest -k week
```

### 4) Типы / «guardrails»
mypy (сейчас проверяет точечно `core/supplements.py`):
```bash
make check-types
```

Полный набор проверок из Makefile:
```bash
make guardrails
```

### 5) Локальная PostgreSQL (dev)
Поднять dev-базу:
```bash
make db-up
```

Остановить dev-базу:
```bash
make db-down
```

Открыть psql внутри контейнера:
```bash
make db-shell
```

Миграция данных (скриптовая):
```bash
make db-migrate
```

Утилиты для отладки/загрузки данных есть в `scripts/` (см. `scripts/README.md`).

## Продакшн / деплой (Docker на сервер)

- Продакшн Compose: `docker-compose.yml` (Postgres + bot).
- Код бота **встраивается в Docker image при сборке**, поэтому для применения изменений требуется **пересборка образа**, а не просто `docker restart`.

Основной сценарий после изменений в коде:
```bash
./deploy.sh
```

Диагностика сервера:
```bash
./scripts/diagnose_server.sh
```

Подробности: `docs/DEPLOYMENT.md`.

Важно: `deploy.sh` использует `sshpass` и содержит доступы/параметры подключения — не дублируй/не логируй их в ответах и PR-описаниях; при необходимости безопаснее вынести такие значения в окружение.

## Архитектура (big picture)

### Точка входа и «склейка» модулей
- `telegram-bot/bot.py`
  - грузит переменные окружения (`dotenv` + `.env` в корне),
  - настраивает логирование в `logs/bot.log`,
  - создаёт `Dispatcher` (aiogram),
  - подключает middleware и routers.

### Middleware
- `telegram-bot/middlewares/auth.py`
  - whitelist-доступ: проверка `config/users.py`,
  - прокидывает `user_id`, `username`, `first_name` в handler data.
- `telegram-bot/middlewares/idempotency.py` (подключается в `bot.py`)
  - дедупликация апдейтов (важно для повторных доставок Telegram).

### Роутеры (handlers)
- `telegram-bot/handlers/commands.py`
  - команды `/start`, `/help`, `/day`, `/week`, `/vitamins` и т.п.
  - `/day` использует `services/nutrition_service.py` + Garmin синхронизацию из `core/garmin_data.py`.
- `telegram-bot/handlers/photo.py`
  - сохраняет фото в `data/media/...`,
  - сначала пытается распознать скриншоты весов (`core/ocr_weight.py`),
  - затем распознаёт меню/еду из фото (`core/menu_parser.py`),
  - если нужно — запрашивает текстовое описание и ведёт диалог через `services/state.py`.
- `telegram-bot/handlers/text.py`
  - если бот ждёт описание после фото — делегирует обратно в `handlers/photo.py` (`handle_description`),
  - иначе запускает LLM-классификацию (`core/llm_router.analyze_message`) и обрабатывает результат.

### Машина состояний (in-memory)
- `services/state.py` — простой in-memory `state_manager`.
- Критичный нюанс: при пересоздании `UserState` легко потерять поля (например `menu_data`). См. `docs/architecture/STATE_MANAGEMENT.md`.

### LLM пайплайн (еда/витамины/вес)
- `core/llm_router.py`
  - формирует system prompt,
  - вызывает OpenAI (HTTP запрос; модель указана в payload),
  - ожидает ответ строго JSON.
- `core/llm_food_processor.py`
  - переводит JSON от router в внутренний формат `meal_items`/`meal_totals`,
  - приоритетно сверяет с локальной продуктовой базой (`core/product_search.py`) и regex-парсером описаний.

### Данные и персистентность (PostgreSQL)
Основной актуальный слой — SQLAlchemy:
- `database/models.py` — модели (users, nutrition_log, weights, supplements_log, activity_log, blood_tests)
- `database/crud.py` — CRUD и агрегации
- `database/__init__.py` — `engine`, `SessionLocal` и re-export CRUD функций

Запись из бота:
- `helpers/db_save.py` — преобразует данные из state/handlers и пишет через `database.crud`.

Чтение для UI:
- `services/nutrition_service.py` — собирает дневную статистику (totals/targets/remaining).

Примечание: есть альтернативный/наследуемый слой `database/repository.py` на `psycopg2` (таблицы вида `*_logs`, `nutrition_entries`). Перед большими изменениями стоит проверить, какой слой реально используется в конкретном участке кода.

## Ключевые документы (из репозитория)
- `README.md` — обзор проекта, базовые команды деплоя/диагностики.
- `docs/ONBOARDING.md` и `docs/QUICK_START.md` — вводная по настройке окружения и ключам.
- `docs/DEPLOYMENT.md` — почему нужен rebuild Docker image и как деплоить.
- `docs/ARCHITECTURE.md` и `docs/HOW_TO_WORK_WITH_CONTEXT.md` — принцип «источник истины = данные на диске/в БД, не контекст чата».
- `scripts/README.md` — как запускать ETL/миграции/отчёты.

## Замечание про перезапуск
В проектной документации явно отмечено: после любых изменений в `.py` коде бот нужно перезапускать (локально — перезапустить процесс; на сервере в Docker — пересобрать образ и перезапустить контейнеры через `./deploy.sh`).
