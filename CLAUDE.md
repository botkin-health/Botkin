# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Открытая платформа трекинга здоровья ([botkin.health](https://botkin.health)).
> Контакты автора на сайте.

---

## 🎯 Vision

Botkin — мультиюзерная система трекинга здоровья с **гибридной приватностью**: семейный сервер (Telegram-бот, Postgres, синки Garmin/Apple Health/Android, дашборд, Tools API с JWT+RLS по cohort) плюс личный Claude пользователя через MCP — для приватных данных, которые остаются только на его компьютере. AI-врач — **BotkinClaw** внутри основного бота. Код открытый; личные данные — только в `~/FamilyHealth/<user>/` (`docs/operations/personal-data.md`). Это не медицинский сервис и не публичный SaaS.

Схема, принципы и что НЕ есть Botkin — `docs/architecture/vision.md`.

## 📚 Где что искать в документации

См. **[docs/INDEX.md](docs/INDEX.md)** — карта-навигатор.

Ключевые точки входа:
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — NOW / NEXT / LATER / VISION / DONE
- **[docs/architecture/decisions/](docs/architecture/decisions/)** — ADR (отвергнутые подходы и почему)
- **[docs/projects/](docs/projects/)** — активные / завершённые / отвергнутые проекты с метками статуса
- **[docs/operations/personal-data.md](docs/operations/personal-data.md)** — куда класть личные данные

---

## Расположение проекта

**Код проекта (эта папка):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin/`

Git remote: `git@github.com:botkin-health/Botkin.git` (перенесён в орг `botkin-health` 14.06.2026; ранее `Lyskovsky/Botkin`, ещё раньше `HealthVault`)

**Медицинские данные семьи (отдельная папка, не путать!):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/`

Там лежат папки с PDF-анализами и knowledge_base.json каждого. У каждой папки свой CLAUDE.md. Это данные — не код.

Если нужно обратиться к медданным из кода/скриптов — путь:
```python
FAMILY_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth"
```

## Пользователи бота (Botkin)

⚠️ **ВНИМАНИЕ — миграция бота (12.05.2026):**
- **Активный бот:** `@Botkin_md_bot` (display name «Botkin», bot_id 8739688481)
- **Прямая ссылка для пользователей:** **t.me/Botkin_md_bot**
- **Старый бот `@HealthVault_bot`** (bot_id 8500310863) — архив, webhook удалён. Истории чатов у юзеров сохраняются, но новые сообщения не обрабатываются.

`@NutriLogBot` БЕЗ префикса — это **чужой украинский бот-двойник**, не наш. Не давать пользователям ссылку `t.me/NutriLogBot`.

Telegram ID и личные данные пользователей — в `~/.claude/CLAUDE.md` (приватный, не в git).

**ВАЖНО:** При SQL-запросах к `nutrition_log` и `supplements_log` ВСЕГДА добавлять `WHERE user_id = 895655` для данных владельца. Без фильтра суммируются калории всех пользователей.

## Навигация по проекту

| Файл | Что содержит |
|---|---|
| `HEALTH.md` | Профиль здоровья: вес, анализы, добавки, давление, цели |
| `knowledge_base.json` | Структурированные данные анализов (JSON) — источник истины |
| `KNOWLEDGE_BASE.md` | Человекочитаемый каталог анализов (дублирует JSON для удобства) |
| `todo.md` | Техдолг и роадмап проекта (без личных целей здоровья — они в HEALTH.md) |
| `docs/ai_context/` | Контекст для AI. **Начни с `README.md`** — там навигация. 01 архитектура · 02 источники данных · 03 схема БД · 04 workflows · 05 помощь с едой · `AI_CHANGELOG.md` |

## Данные здоровья — ключевое

Полный реестр источников, скриптов и форматов — `docs/ai_context/06_health_data_pipeline.md` (и `02_data_sources.md`). Под рукой держать:

- **Анализы (KB).** Источник истины — `~/FamilyHealth/<Имя>/knowledge_base.json` на маке. На сервере два места: Postgres `blood_tests` (его читают дашборд и агент) и `/app/data/kb/kb_<id>.json`. Ключи канонизируются **на чтении** — `core/health/kb_schema.py` (алиасы, единицы, US→метрика).
- **Добавил анализ в KB** → `python3 scripts/sync_user_health.py --user <tg_id> --apply` (или `--all`). ⚠️ Льёт из **локального** KB: если на сервере данных больше — сначала дополни локальный, иначе перезатрёшь.
- **`/doc` в боте** пишет в `blood_tests` напрямую, мимо мака. Этих данных нет в локальном KB.
- **Apple Health:** основной канал — Health Auto Export → `POST /apple_health_v2` (`telegram-bot/webhook/apple_health.py`), тренировки — отдельным POST. `/apple_health` v1 — бесплатный путь через iOS Shortcuts, **не legacy**.
- **Android:** Health Connect → приложение HC Webhook → `POST /android_health_v1` (`telegram-bot/webhook/android_health.py`).
- ⚠️ `data/apple_health_steps_daily.json` **задвоен для 2023+** — для шагов с 2023 года брать Garmin `data/garmin/daily-summary/`.

## Команды разработки

### Тесты

```bash
# Запуск всех unit-тестов (integration и live LLM исключены по умолчанию)
PYTHONPATH=. pytest tests/ -v \
  --ignore=tests/integration \
  --ignore=tests/test_nutrition_parsing.py

# Запуск одного файла
PYTHONPATH=. pytest tests/test_nutrition_logic.py -v

# Запуск одного теста
PYTHONPATH=. pytest tests/test_nutrition_logic.py::test_xxx -v

# Env-переменные НЕ нужны: dummy-ключи ставит tests/conftest.py (setdefault +
# autouse-фикстура, защищающая от реальных LLM-вызовов за деньги).
# DATABASE_URL не нужна — conftest.py создаёт in-memory SQLite
```

### Линтинг

```bash
# Проверить линтером
ruff check .

# Проверить форматирование
ruff format --check .

# Автоисправление
ruff check --fix .
ruff format .
```

Конфигурация ruff — в `pyproject.toml`. Строки >120 символов игнорируются (E501 — LLM-промпты намеренно длинные).

### Деплой на сервер (Hetzner 116.203.213.137)

**Деплой — только через GitHub Actions.** Workflow «Deploy prod» (`.github/workflows/deploy-prod.yml`):

```bash
# Запуск из CLI (ветка по умолчанию main)
gh workflow run deploy-prod.yml -f branch=main

# Откат на готовый образ — сборка пропускается
gh workflow run deploy-prod.yml -f image_tag=<готовый-тег-образа>
```

Либо вручную: Actions → «Deploy prod» → Run workflow. Workflow собирает Docker-образ бота, пушит в GHCR (`ghcr.io/botkin-health/botkin-bot`), затем по SSH на сервере (каталог `/opt/botkin`) выполняет `docker compose -f docker-compose.prod.yml pull && up -d --wait` (pull-only, **без сборки на сервере**). Файл `.env` лежит на сервере (`/opt/botkin/.env`), в репозиторий не входит. Подробнее — `docs/DEPLOYMENT.md`.

**Ветки:** `dev` → авто-деплой на дев-стенд (`@botkin_dev_bot`); `main` → прод через PR `dev → main` и «Deploy prod».

**Миграции деплоем НЕ катятся.** Отдельный workflow «Migrate DB»: `gh workflow run migrate.yml -f environment=dev|prod` (сам делает бэкап). `alembic` выполняется **внутри контейнера бота**, поэтому порядок: сначала Deploy, сразу за ним Migrate. После — сверить `SELECT version_num FROM alembic_version`. ⚠️ На проде бывают ограничения, которых нет в моделях (прецедент: `uq_workouts_user_start`) — перед миграцией смотреть `\d <таблица>` на проде.

**Что сейчас на проде:** `grep IMAGE_TAG /opt/botkin/.env` на сервере — тег образа; дельта к релизу — `git log --oneline <тег>..origin/dev`. Что `dev` сильно впереди `main` — норма: копится до релиза.

**Лендинг botkin.health** деплоится вручную (nginx из `/opt/botkin-site/`), `git push` сайт **не** обновляет — `docs/landing/README.md`.


### Диагностика сервера

⚠️ Пачку ssh-подключений подряд сервер может сбросить (`Connection closed … port 22`). Это **не fail2ban** — наш IP в `ignoreip`, а `MaxStartups` в sshd: сброс мгновенный, ждать не нужно, повтори через пару секунд. Лучше батчить команды в одну сессию.

```bash
# Логи бота (последние 50 строк)
ssh root@116.203.213.137 "docker logs healthvault_bot --tail 50"

# Статус контейнера
ssh root@116.203.213.137 "docker ps | grep healthvault"

# Рестарт бота
ssh root@116.203.213.137 "docker restart healthvault_bot"

# psql на сервере
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault"

# Диагностика общего состояния
./scripts/util/diagnose_server.sh
```

### Синк данных здоровья

```bash
# Синк KB конкретного пользователя (bind-mount + Postgres)
python3 scripts/sync_user_health.py --user 895655 --apply

# Все пользователи
python3 scripts/sync_user_health.py --all --apply
```

---

## Skills (Claude Code)

- `/sync` — обновить все источники данных, показать таблицу актуальности
- `/cleanup` — коммит, пуш, бэкап БД, удаление мусора

## Секреты и токены

API-ключи — `.env` / `.env.production`; OAuth-токены — `data/cache/` (в `.gitignore`). Где что лежит, `sshpass` и правильный порядок Zepp reauth — `docs/operations/secrets-and-tokens.md`.

## Анти-паттерны кода (не повторять)

- ❌ Импортировать `core.llm_router`, `core.menu_parser` и другие proxy-shims из корня `core/` — это re-exports из рефакторинга 22.03.2026. Импортировать напрямую: `from core.llm.router import …`, `from core.vision.menu_parser import …`
- ❌ `SELECT … FROM nutrition_log` без `WHERE user_id = X` — суммируются все пользователи
- ❌ Писать новые поля в таблицу `users` — настройки и цели живут в `user_settings`
- ❌ Читать поле `totals->>'fat'` — поле называется `totals->>'fats'` (множественное число)
- ❌ FK на `users.id` — PK таблицы users это `telegram_id` (BigInt), не синтетический `id`
- ❌ Читать items только по одному ключу (`it["food"]`) — есть 3 схемы одновременно; использовать `_item_name()` из `core/food/fiber_table.py`
- ❌ Писать items без поля `fiber` — прогонять через `enrich_items_with_fiber()` перед INSERT
- ❌ Писать в orphan-таблицы `daily_summaries / sleep_records` — они не управляются ORM и пусты на проде. В `blood_pressure_logs / workouts` пишут только штатные raw-SQL пути (`webhook/apple_health.py`, `webhook/agent_tools/`) — новые записи добавлять через них, не через ORM
- ❌ **Держать открытую транзакцию Postgres поперёк долгого сетевого вызова** (LLM, внешний API). Сессии живут с `idle_in_transaction_session_timeout` (15с, `database/__init__.py`) — Postgres обрывает такое соединение, следующий запрос падает с `OperationalError`. Перед сетью закрывать транзакцию (`_end_open_tx` в `core/agent_chat.py`). Транзакцию открывают не только записи: после `commit()` ORM-объект истекает (`expire_on_commit=True`), и **чтение его атрибута** тянет refresh-SELECT. Прецедент #347 (26.07.2026): агент терял ответы, и чем содержательнее ответ — тем вероятнее терялся
- ❌ Ронять уже полученный от LLM ответ из-за сбоя записи в БД — генерация оплачена. Логировать сбой персистентности, но ответ пользователю отдавать (`_persist_turn`)

---

## Хронолог разработки в Notion

Страница «Хронолог разработки» (`37bf1efb-961b-81cd-9145-cc24bca86e96`). Писать, когда изменение заметно **пользователям** — внутренний тулинг, CI и рефакторинг сюда не идут (для них `docs/ai_context/AI_CHANGELOG.md`). Автор записи — реальный автор PR, человекочитаемо по-русски: `Igor-Lysk` → Игорь Лысковский, `Lyskovsky` → Александр Лысковский, `Alegas` → Олег Лысковский; незнакомого — уточнить, не угадывать.

Формат записи, правила и как вставлять, не сжигая токены, — `docs/operations/notion-chronolog.md`.

## Важные правила

- **Язык**: всегда общаться с пользователем на русском
- **AI_CHANGELOG**: после каждой задачи обновлять `docs/ai_context/AI_CHANGELOG.md`
- **Research-grounded решения — фиксировать durable**: если нетривиальное решение опирается на внешний ресёрч / опыт сообщества / реверс-инжиниринг (особенно интеграции с неофициальными API), оформить **ADR** в `docs/architecture/decisions/` (+ строка в индексе README) и, если есть повторяющиеся грабли — раздел **«Known issues / troubleshooting»** в соответствующем research-доке `docs/researches/`, **со ссылками на источники**. Цель: сторонний разработчик понимает *что делали, почему и на чём основано* без археологии по issue. Issue/PR/коммиты — не замена durable-докам. Пример: [ADR-0005](docs/architecture/decisions/0005-cgm-librelinkup-integration.md) (CGM/LibreLinkUp).
- **Notion Хронолог**: обновлять страницу `37bf1efb-961b-81cd-9145-cc24bca86e96`, когда изменение важно для всех участников проекта (не только отдела разработки) — см. раздел «Хронолог разработки в Notion»
- **Синк перед анализом**: всегда запускать `/sync` перед анализом данных здоровья
- **knowledge_base.json**: при добавлении новых анализов/УЗИ/МРТ/ЭКГ — обновлять этот файл
- **Бэкап**: БД на удалённом сервере, не на localhost. Для записи в БД нужен SSH к серверу.

## Протокол чтения медданных (КРИТИЧНО)

**При ЛЮБОМ вопросе о здоровье любого пользователя — порядок чтения строго такой:**

1. **`PROFILE.md`** в папке человека (`FamilyHealth/{Имя} — Здоровье/PROFILE.md`):
   - **Сначала «🩺 Журнал обследований»** (между маркерами `<!-- EXAM_JOURNAL_START -->...END -->`) — это автогенерируемый индекс **что и когда** обследовалось. Никогда не предлагать сделать обследование, не сверившись с журналом.
   - Затем основная часть — карта диагнозов и хронических состояний.
2. **`knowledge_base.json`** в той же папке — детали из журнала. Секции:
   - `blood_tests`, `urine_tests`, `hormones`, `vitamins`, `genetics` — лабораторные
   - `ultrasound` — УЗИ (все типы: ОБП, почки, простата, щитовидка, ЭхоКГ, БЦА, малый таз, молочные)
   - `medical_records` — **приёмы врачей часто содержат embedded summary с ЭКГ/ЭхоКГ/УЗДГ/ЭГДС/колоноскопией** (например, 2021-03-01 atlas_therapist — там весь комплекс Атласа)
   - `ecg`, `spirometry`, `sports_tests` — функциональные тесты
3. **Только после этого** — читать отдельные PDF/docx для деталей, которых нет в JSON.

**⚠️ Граница «источника истины» — по типу данных (уточнено 12.07.2026):**
- **Живые ежедневные потоки** — питание (`nutrition_log`), БАДы (`supplements_log`), вес/состав тела (`body_measurements`), глюкоза (`glucose_readings`), функциональные замеры (сила хвата и т.п.) — **первичны в БД Botkin (Postgres на сервере), локальный `knowledge_base.json` для них может быть УСТАРЕВШИМ**. По ним читать сначала БД (agent_tools / psql), KB — только бэкап.
- **Курируемые документы** — анализы крови, генетика, УЗИ/МРТ, мед.записи — первичны в `knowledge_base.json` на маке (я их парсю и завожу).
- Направление желаемой эволюции (по решению Александра 12.07): постепенно перейти на работу через Botkin как основную систему, локальную KB держать как бэкап и периодически обновлять снимок из БД (dump DB → JSON). Маркер продублирован первой строкой каждого `knowledge_base.json` (`_source_of_truth`).

**Если добавили новые анализы/УЗИ в `knowledge_base.json` — обязательно регенерировать журнал:**
```bash
python3 scripts/generate_exam_journal.py "Имя — Здоровье" --update-profile
```

**Главные ошибки прошлого** (не повторять!):
- ❌ Игнорировать `medical_records.summary` — там часто весь комплекс приёма (УЗИ + ЭКГ + ЭхоКГ).
- ❌ Цитировать прозу из HEALTH.md/PROFILE.md как «снимок состояния» — она может устаревать. JSON и журнал обследований — единственный источник истины.
- ❌ Предлагать сделать ЭКГ/УЗИ ОБП/колоноскопию, не глянув в журнал — там может быть свежее. **Прецедент 09.05.2026:** AI забыл про УЗИ ОБП в МЕДСИ от 19.04.2026 и предложил сделать его «впервые с 2021».

**Никаких параллельных md-черновиков к обследованиям.** Развёрнутая интерпретация — в `knowledge_base.json` в полях `summary`/`conclusion`/`recommendations`. JSON — единственный источник истины, PDF/docx — архив оригиналов.

## Правила аналитики и отображения данных

- **Факт vs среднее — не путать.** Когда пишешь «было X → стало Y», X и Y должны быть реальными замерами (первый и последний), а не средними за неделю. Средние за неделю — это отдельная метрика, которую нужно явно подписывать «(средняя за неделю)».
- **Не сглаживать молча.** Любая трансформация данных (усреднение, детренд, фильтрация) должна быть явно указана. Пользователь знает свои цифры — если написать 81.7 вместо реальных 82.75, он заметит и потеряет доверие к анализу.
- **Корреляция ≠ причина.** Два показателя могут коррелировать только потому что оба плавно меняются со временем (тренд). Перед выводами всегда проверять: это связь дневных колебаний (детренд) или ложная корреляция трендов? Пример: «вес падает + температура растёт» → r=−0.49, но после детренда r=+0.19 (ноль). Реальная причина потери веса — питание и тренировки, а не весна.
- **Указывать размер выборки.** Корреляция на 12 днях — предварительная гипотеза. На 70+ днях — устойчивый сигнал. Всегда писать (N дней) рядом с r.
- **Не дублировать числа.** Если число уже есть в одной колонке таблицы (например «29 до 21.03»), не повторять его в другой (например «29 тренировок» в статусе).

## Семейное хранилище медицинских данных (FamilyHealth)

**Google Drive — единственный источник истины для медицинских документов всех членов семьи.**

Локальный путь (синхронизируется автоматически):
```
/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/
```

Короткая ссылка в коде: `GD_HEALTH` (задать через переменную окружения или хардкод).

### Структура

Папки по каждому члену семьи — см. `~/.claude/CLAUDE.md` (имена, возраст, диагнозы там).

### Правила работы с данными семьи

- **НИКОГДА не путать данные разных людей.** Каждый человек = отдельная папка, отдельный knowledge_base.json
- Каждая папка содержит `PROFILE.md` (диагнозы) и `knowledge_base.json` (все обследования)
- knowledge_base.json в корне проекта — данные ТОЛЬКО owner-cohort
- Данные бота (PostgreSQL) — только пользователи бота (см. `~/.claude/CLAUDE.md`)
- Именование файлов: `{тип}_{YYYY-MM-DD}_{лаборатория}_{подтип}.{ext}`

## BotkinClaw — AI-агент (in-process)

Живёт **внутри** основного бота: `core/agent_chat.py:ask_agent()` → Anthropic Messages API; история — таблица `agent_conversations`; тулы — `telegram-bot/webhook/agent_tools/` (JWT+RLS по cohort). Доступен **любому** зарегистрированному пользователю; `users.agent_system_prompt` — опциональный override, а не гейт.

Медпрофиль (аллергии, хроники, постоянные лекарства) — `users.onboarding_data`, единый реестр ключей — `core/health/onboarding_lists.py`. ⚠️ Онбординг хроники и лекарства **не спрашивает** — профиль сам не заполнится.

Тулы, кто что пишет и читает — `docs/ai_context/botkinclaw.md`; почему не NanoClaw — ADR-0002.

## Архитектура проекта (код)

```
Botkin/                          # ~/Botkin/ — ТОЛЬКО КОД И OPERATIONAL DATA
├── config/                      # Настройки, пользователи
├── core/                        # Бизнес-логика (LLM, питание, парсеры)
├── database/                    # SQLAlchemy модели, CRUD, миграции
├── domain/                      # Доменные модели
├── services/                    # Сервисный слой
├── telegram-bot/                # Aiogram бот (handlers, middlewares)
├── scripts/                     # Импорт данных, анализ, бэкфилл
├── tests/                       # Pytest (unit + LLM prompt тесты)
├── data/                        # Operational data (JSON, CSV, кэш, медиа бота)
│   ├── garmin/                  # Garmin API данные (шаги, сон, HRV)
│   ├── nutrition/               # JSON-логи питания
│   ├── media/                   # Фото еды, голосовые
│   ├── cache/                   # Токены OAuth
│   └── ...                      # НЕ медицинские документы (те на Google Drive)
├── knowledge_base.json          # KB владельца (источник истины для его анализов)
├── docs/                        # Документация + ai_context/
└── archive/                     # Архив старого кода
```

---

## Agent skills

Per-repo config consumed by the Matt Pocock engineering skills (`to-issues`, `triage`, `qa`, `review`, `tdd`, `improve-codebase-architecture`, etc.).

### Issue tracker

Issues live in the `botkin-health/Botkin` GitHub Issues, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) — defaults, label strings equal role names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo: one `CONTEXT.md` (lazy) + ADRs at `docs/architecture/decisions/`. See `docs/agents/domain.md`.

---

[← Документация Botkin — Index](docs/INDEX.md)
