# Документация Botkin — Index

Карта-навигатор. Если ищешь что-то — начни отсюда.

---

## 🎯 Понять проект

| Вопрос | Куда смотреть |
|---|---|
| Что такое Botkin, куда движется | [`../CLAUDE.md`](../CLAUDE.md) — vision и архитектурные принципы |
| Что в работе сейчас / что дальше | [`ROADMAP.md`](ROADMAP.md) — NOW / NEXT / LATER / VISION / DONE |
| История по версиям | [`../CHANGELOG.md`](../CHANGELOG.md) (если есть) или релизы на GitHub |
| История по сессиям с Claude | [`ai_context/AI_CHANGELOG.md`](ai_context/AI_CHANGELOG.md) |

## 🏗 Архитектура и решения

| Вопрос | Куда смотреть |
|---|---|
| Текущая архитектура (data flow, компоненты) | [`ai_context/01_architecture.md`](ai_context/01_architecture.md) |
| Что откуда тянется (источники данных) | [`ai_context/02_data_sources.md`](ai_context/02_data_sources.md) |
| Схема БД, таблицы, конвенции | [`ai_context/03_database_schema.md`](ai_context/03_database_schema.md) |
| Workflow'ы разработки | [`ai_context/04_workflows.md`](ai_context/04_workflows.md) |
| **ADR — почему такой выбор / почему отвергнут подход** | [`architecture/decisions/`](architecture/decisions/) |
| **Активные проекты со статусом** | [`projects/`](projects/) — каждая папка имеет `STATUS.md` |
| State management | [`architecture/STATE_MANAGEMENT.md`](architecture/STATE_MANAGEMENT.md) |

## 🛠 Операции и деплой

| Вопрос | Куда смотреть |
|---|---|
| Как деплоить | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Бэкап и восстановление | [`BACKUP_GUIDE.md`](BACKUP_GUIDE.md), [`RESTORE_BACKUP.md`](RESTORE_BACKUP.md) |
| Cron-задачи на сервере | [`CRON_SETUP.md`](CRON_SETUP.md) |
| Релизный workflow | [`RELEASING.md`](RELEASING.md) |
| **Куда класть личные данные (privacy)** | [`operations/personal-data.md`](operations/personal-data.md) |
| Архитектурный аудит проекта | [`2026-04-21-architectural-review.md`](2026-04-21-architectural-review.md) |

## 👥 Пользователи и онбординг

| Вопрос | Куда смотреть |
|---|---|
| Пользовательский гид (mkdocs) | [`user_guide/ru/docs/`](user_guide/ru/docs/) |
| Скриншоты бота | [`user_guide/screenshots/`](user_guide/screenshots/) |
| Лендинг botkin.health | [`landing/`](landing/) |

## 🔬 Research и идеи

| Вопрос | Куда смотреть |
|---|---|
| Wearables MCP review | [`research/2026-04-17_wearables-mcp.md`](research/2026-04-17_wearables-mcp.md) |
| Decision history (NanoClaw, и т.п.) | [`architecture/decisions/`](architecture/decisions/) |

## 🧪 Контекст для AI и data analysis

| Вопрос | Куда смотреть |
|---|---|
| Как анализировать данные пользователя | [`DATA_ANALYSIS_PROTOCOL.md`](DATA_ANALYSIS_PROTOCOL.md) |
| Контекст для логирования еды | [`ai_context/05_food_logging_context.md`](ai_context/05_food_logging_context.md) |
| Промпт для LLM-парсера еды | [`PROMPT_FOR_CLAUDE_MEAL_FORMAT.md`](PROMPT_FOR_CLAUDE_MEAL_FORMAT.md) |
| ЕМИАС экстракция | [`emias_extraction_guide.md`](emias_extraction_guide.md) |
| Garmin authentication | [`ai_context/GARMIN_AUTH_GUIDE.md`](ai_context/GARMIN_AUTH_GUIDE.md) |
| Longevity benchmarks | [`LONGEVITY_BENCHMARKS.md`](LONGEVITY_BENCHMARKS.md) |
| Reference: Wellally blueprint | [`ai_context/reference_wellally_blueprint.md`](ai_context/reference_wellally_blueprint.md) |

---

## 📌 Куда что писать (правила процесса)

| Когда | Куда |
|---|---|
| Принял архитектурное решение (выбрал подход / отверг альтернативу) | Создать **ADR** в `architecture/decisions/NNNN-<slug>.md` (см. шаблон) |
| Начал новый многошаговый проект | Создать папку `projects/YYYY-MM_<name>/` с `STATUS.md`, `SPEC.md`, опционально `PLAN.md` |
| Завершил проект | В `STATUS.md` сменить статус → `COMPLETED`, обновить ROADMAP DONE |
| Отверг проект / спека стала obsolete | Статус → `REJECTED` или `DEFERRED`, **не удалять файл** (это история мышления) |
| Изменился horizon (NOW/NEXT/LATER/VISION) | Обновить `ROADMAP.md` |
| Закончил сессию с большим объёмом изменений | Дописать в `ai_context/AI_CHANGELOG.md` |
| Выпустил версию | Обновить `pyproject.toml`, тег, GitHub Release |
| Хочу сохранить research / discovery (новая технология, обзор) | `research/YYYY-MM-DD_<topic>.md` |
| Личные медданные / цели здоровья | **НЕ в репо.** Только в `~/FamilyHealth/<user>/` (см. `operations/personal-data.md`) |

---

## 🔒 Чего НЕ должно быть в публичном репо

См. [`operations/personal-data.md`](operations/personal-data.md) — полный чек-лист.

Короче:
- Имена реальных пользователей (только cohort-термины: owner / family / early_user / external)
- Диагнозы конкретных людей
- user_id, telegram_id, email, телефоны
- Полные пути к личной Google Drive папке
- Биомаркеры с цифрами конкретных людей
- Личные цели здоровья (анализы, био-возраст, тренировки)
