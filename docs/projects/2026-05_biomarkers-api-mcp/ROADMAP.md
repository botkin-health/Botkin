# Roadmap: Biomarkers API + MCP

> Каждый спринт = одна сессия 2-3 часа. Acceptance criteria — конкретное действие, которое можно протестировать после спринта. Если acceptance не пройдёт — спринт не считается завершённым.

---

## Спринт 1 — MCP-сервер базовый (≈2-3 ч)

### Что делаем

1. Создать локальный пакет `~/Tools/botkin-mcp/` на маке Александра (Python, на основе [mcp-sdk-python](https://github.com/modelcontextprotocol/python-sdk)).
2. Сервер регистрируется в `~/.claude/claude_desktop_config.json` под именем `botkin`, стартует по stdio.
3. Внутри — один tool: `botkin_get_dashboard()`. Делает HTTP-вызов на `https://botkin.health/api/agent/dashboard` с JWT из `~/.botkin/jwt.token`.
4. JWT-токен генерируется одноразово через скрипт `scripts/issue_agent_jwt.py` (уже есть в проекте — см. `agent_tools_api.py` для формата).
5. Тест: запустить Claude Desktop, в новом чате ввести «покажи мой PhenoAge» — я должен сделать tool call и вернуть свежие данные с сервера.

### Зачем именно этот спринт первый

Самый дешёвый способ убедиться что вся цепочка (MCP → API → БД → ответ) работает end-to-end. Дальше расширять — несложно. И сразу даёт пользу: после этого спринта мне (Claude) больше не нужен файловый доступ к knowledge_base.json — я хожу на сервер.

### Acceptance criteria

- [ ] `botkin-mcp` пакет работает локально (`python -m botkin_mcp.server` стартует без ошибок)
- [ ] В Claude Desktop config зарегистрирован MCP-сервер `botkin`
- [ ] При запросе «покажи мой PhenoAge» Claude делает `botkin_get_dashboard` и получает JSON-ответ
- [ ] В ответе содержится свежий `bio_age_est` (35.7) и `bio_age_est_corrected` (33.2)
- [ ] Если выключить интернет — Claude вернёт понятную ошибку «сервер недоступен», не зависнет

### Файлы

- НОВОЕ: `~/Tools/botkin-mcp/botkin_mcp/server.py`
- НОВОЕ: `~/Tools/botkin-mcp/pyproject.toml`
- НОВОЕ: `~/.botkin/jwt.token`
- НОВОЕ: `scripts/issue_agent_jwt.py` *(если ещё нет в проекте)*
- ИЗМ: `~/.claude/claude_desktop_config.json` — секция `mcpServers.botkin`

---

## Спринт 2 — MCP-сервер расширенный (≈2-3 ч)

### Что делаем

Добавить 8-10 tools поверх базы из спринта 1:

| Tool | Endpoint | Что возвращает |
|---|---|---|
| `botkin_get_workouts` | `/api/agent/workouts?days=N` | последние N тренировок с метриками Garmin |
| `botkin_get_nutrition` | `/api/agent/nutrition?days=N` | питание за период (kcal/protein/fats/carbs/fiber, по дням) |
| `botkin_get_weights` | `/api/agent/weights?days=N` | замеры веса + body_fat |
| `botkin_get_biomarkers` | `/api/agent/biomarkers` | все биомаркеры с историей и датами |
| `botkin_get_sleep_hrv` | `/api/agent/sleep?days=N` | Garmin сон + HRV + body battery |
| `botkin_get_blood_pressure` | `/api/agent/bp?days=N` | давление по дням |
| `botkin_get_screen_time` | `/api/agent/screen_time?days=N` | Mac+iPhone Screen Time |
| `botkin_get_environment` | `/api/agent/environment?days=N` | Netatmo CO₂/temp + погода |
| `botkin_search_kb` | `/api/agent/kb/search?q=...` | full-text по knowledge_base.json *(до спринта 4)* |

Кэш ответов 30 сек чтобы не дёргать API при последовательных вопросах.

### Acceptance criteria

- [ ] «Как я спал последние 7 дней?» — отвечаю с реальными цифрами за 7 ночей
- [ ] «Покажи всю динамику ЛПНП за 2026 год» — отвечаю с временной шкалой
- [ ] «Какой CO₂ был в спальне на этой неделе?» — отвечаю с дневными цифрами Netatmo
- [ ] Я больше **никогда** не лезу в `~/FamilyHealth/Александр.../knowledge_base.json` напрямую — все ответы через MCP

### Файлы

- ИЗМ: `~/Tools/botkin-mcp/botkin_mcp/server.py` — +9 tools
- ИЗМ: `telegram-bot/webhook/agent_tools_api.py` — добавить недостающие endpoints

---

## Спринт 3 — PDF/JPEG-парсер в боте (≈2-3 ч)

### Что делаем

1. Новый handler в `telegram-bot/handlers/` на входящие PDF/фото в `@Botkin_md_bot`.
2. Handler определяет: это анализ крови / УЗИ / МРТ / другое?
3. Если анализ крови — отправляет PDF в Anthropic Claude API (модель умеет читать PDF и изображения напрямую) с промптом «извлеки все биомаркеры в JSON: name, value, unit, ref_range, date, lab».
4. Сохраняет результат в новую таблицу `parsed_biomarkers (id, user_id, source, raw_json, parsed_at, confirmed_by_user)`.
5. Бот отвечает: *«Распознал N маркеров от {date} в {lab}: ТТГ 2.12 мМЕ/л, ферритин 242 нг/мл, …. Подтверди или поправь:»* — кнопки подтверждения / редактирования.
6. После подтверждения — данные коммитятся в финальную таблицу `biomarkers` (создаётся в спринте 4). Оригинал PDF из Telegram **удаляется** (`bot.delete_message` для своего сообщения с PDF), у пользователя остаётся он в его исходящих.

### Acceptance criteria

- [ ] Александр кидает любой свой PDF анализа в `@Botkin_md_bot` → через ≤60 сек получает распознанный список
- [ ] Точность ≥95% по полю `value` на тестовом наборе из 5 разных лабораторий (CMD, Хеликс, Инвитро, КДЛ, Атлас)
- [ ] Кнопка «Подтвердить» сохраняет данные в БД
- [ ] PDF из Telegram удаляется после подтверждения, оригинал остаётся в Telegram-чате у пользователя

### Файлы

- НОВОЕ: `telegram-bot/handlers/biomarker_pdf.py`
- НОВОЕ: `core/health/biomarker_parser.py` — обёртка над Anthropic Claude API
- ИЗМ: `database/init.sql` — добавить таблицу `parsed_biomarkers`

---

## Спринт 4 — Дашборд читает биомаркеры из БД (≈2-3 ч)

### Что делаем

1. Создать финальную таблицу `biomarkers (id, user_id, name, value, unit, ref_low, ref_high, date, source, recorded_at)` с RLS.
2. Миграционный скрипт: импорт текущего `telegram-bot/biomarkers_895655.json` в БД для Александра как первый пользователь.
3. Refactor `_build_payload` в `telegram-bot/dashboard_generator.py`: убрать чтение `biomarkers_{user_id}.json`, заменить на SQL-запросы.
4. После подтверждения данных в спринте 3 — автоматический коммит из `parsed_biomarkers` в `biomarkers`.
5. Удалить deprecated `scripts/generate_biomarkers_json.py` (не сразу — мы пока хотим уметь экспортить).

### Acceptance criteria

- [ ] Александр кидает свежий PDF → бот парсит → подтверждает → **через ≤90 сек** дашборд показывает новые цифры (без участия мака)
- [ ] Никаких упоминаний `biomarkers_*.json` в `dashboard_generator.py`
- [ ] `bio_age_est` (PhenoAge), `Attia`, `LE8`, `Мониторинг` — все читают из БД
- [ ] Креатин-флаг (артефакт от добавки) продолжает работать (он уже на supplements_log, не на biomarkers)
- [ ] Опционально: команда `/export_biomarkers` в боте возвращает JSON-дамп = аналог старого `biomarkers_895655.json`

### Файлы

- ИЗМ: `database/init.sql` — таблица `biomarkers`
- ИЗМ: `telegram-bot/dashboard_generator.py` — секция `# ── biomarkers: try to load from per-user JSON in container ──`
- НОВОЕ: `scripts/migrate_biomarkers_json_to_db.py`

---

## Спринт 5 — Multi-user онбординг (≈2-3 ч)

### Что делаем

1. Команда `/onboard_biomarkers` в боте: новый пользователь кидает свои свежие анализы → у него заводится свой набор в БД.
2. Каждый получает индивидуальный `botkin.health/mc/{share_token}` с дашбордом по своим данным.
3. RLS на `biomarkers` и `parsed_biomarkers` уже из спринта 4 — каждый видит только свои.
4. Помощник в боте: «Покажи свои последние результаты», «Что у меня изменилось с прошлого раза».

### Acceptance criteria

- [ ] Андрею даю ссылку на `@Botkin_md_bot` → он отправляет PDF своего анализа → через ≤2 мин у него рабочий дашборд по адресу `botkin.health/mc/{его_share_token}`
- [ ] Александр не видит данных Андрея в своём дашборде (RLS работает)
- [ ] Андрей не видит данных Александра в своём дашборде
- [ ] Дашборд адаптирован к scale-up: показывает то что есть, не падает на отсутствии редких маркеров

### Файлы

- ИЗМ: `telegram-bot/handlers/onboarding.py` (или новый)
- ИЗМ: `telegram-bot/webhook/dashboard.py` — может потребоваться адаптация под per-user тип данных

---

## Спринт 6 — GDrive Service Account *(опционально, для папы)*

### Что делаем

Папа не очень в Telegram, у него уже есть папка в Google Drive с PDF-анализами. Решение:

1. Создать GCP Service Account, выдать ему read-only доступ к папе папке.
2. Cron-job на сервере: раз в сутки ходит в GDrive, скачивает новые PDF, парсит, заносит в БД, удаляет локальный временный файл.
3. Папа просто **кладёт PDF в свою папку GDrive** — больше ничего не делает.

### Acceptance criteria

- [ ] Папа кладёт новый PDF в `Google Drive / FamilyHealth / Павел — Здоровье /` → к утру следующего дня данные в его дашборде
- [ ] Никаких маков в pipeline. Никакого Telegram участия.
- [ ] Лог обработки в `/var/log/botkin_gdrive_sync.log`

### Файлы

- НОВОЕ: `scripts/import/gdrive_biomarker_sync.py`
- ИЗМ: `scripts/server/sync_all.sh` — добавить шаг `gdrive`
- НОВОЕ: GCP Service Account JSON в `data/cache/gdrive_sa.json` (gitignore)

---

## Что после полного завершения

- `knowledge_base.json` остаётся как **исторический бэкап** на маке у Александра. Каждый из семьи может скачать свой JSON-дамп через `/export_biomarkers` в боте.
- Дашборд работает identично для всех 6+ пользователей.
- Будущее iOS/Android-приложение пишется поверх готового `agent_tools_api.py`.
- Старые скрипты `scripts/generate_biomarkers_json.py`, `scripts/generate_exam_journal.py` — deprecated, удаляются.

---

## Tech debt которое появится по дороге

- **Качество парсинга PDF** Claude-моделью на разных лабораториях — нужно мониторить, потенциально подкручивать промпт
- **Стоимость Anthropic API** для парсинга — пока маленький объём, ~$0.05/PDF, ОК до сотен PDF в месяц
- **Дедупликация** — если пользователь кинет тот же PDF два раза, не сохранять второй раз
- **Историческая миграция** для семьи — у Андрея/Олега/Ники есть архивы PDF за годы. Нужен ли batch-импорт или достаточно «с этого момента»?
- **Конфиденциальность парсинга** — Anthropic API использует данные пользователя для inference, не для обучения (по их TOS) — нужно зафиксировать в `docs/operations/personal-data.md`
