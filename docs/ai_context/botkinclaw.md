# BotkinClaw — AI-агент (in-process)

> Перенесено из корневого `CLAUDE.md` 23.09.2026 дословно: раздел справочный и нужен не в каждой задаче,
> а CLAUDE.md целиком загружается в каждую сессию Claude Code. Источник истины по этой теме — этот файл.


AI-врач живёт **внутри** основного aiogram-бота (`@Botkin_md_bot`), не в отдельном контейнере.

- **Точка входа:** `core/agent_chat.py:ask_agent()` — прямой вызов Anthropic Messages API (Claude)
- **История диалога:** таблица `agent_conversations` в Postgres (DDL: `database/migrations/add_agent_chat.sql`)
- **Tools:** 40+ endpoints в пакете `telegram-bot/webhook/agent_tools/` (19 модулей; монолит `agent_tools_api.py` разрезан 08.09.2026, коммит `5d93ece`). JWT+RLS изоляция по cohort; актуальный список:
  ```bash
  grep -rhoE '@router\.(get|post)\("/[a-z_]+"' telegram-bot/webhook/agent_tools/*.py | sort -u
  ```
- **JWT-контракт:** каждый запрос агента несёт `user_id` + `cohort` — RLS автоматически ограничивает видимость данных
- **Доступ — у всех (#165, 18.06.2026):** разговорный агент работает для **любого** зарегистрированного пользователя. `users.agent_system_prompt` — **опциональный override** (богатая семейная персона из `onboard_family_user.py`), а НЕ гейт. Если он пуст — `ask_agent` использует `build_default_agent_prompt(user)` (лёгкий промпт из `onboarding_data`). Никакого деления на «семью» для доступа к агенту.

Ключевые agent tools: `get_weight_history`, `get_body_measurements`, `get_day_summary`, `get_indoor_air`, `get_outdoor_weather`, `get_user_settings`, `recent_workouts`, `recent_biomarkers`, `phenoage`, `kb_value`, `list_kb_keys`.

Решение принято 21.05.2026 вместо NanoClaw (отдельной контейнерной инфры). Подробнее — [ADR-0002](docs/architecture/decisions/0002-rejecting-nanoclaw-for-simpler-agent.md).

### Медпрофиль пациента: аллергии, хроники, постоянные лекарства

Живёт в `users.onboarding_data` (JSONB). Единый реестр ключей и сплиттер свободного текста — **`core/health/onboarding_lists.py`** (`CONDITION_KEYS`, `ALLERGY_KEYS`, `onboarding_list`, `split_freetext`). Новые читатели/писатели подключать только через него — «куда пишем» должно совпадать с «откуда читаем».

⚠️ **Онбординг-квиз про хроники и лекарства НЕ спрашивает** — шаг убран в `f366c98` («value-first quiz»), legacy-шаг `chronic` ремапится на `artifact`. Не искать этот вопрос в онбординге и не считать, что профиль заполнится сам.

| | Кто | Что делает |
|---|---|---|
| **Пишут** | `/doc` (`telegram-bot/handlers/doc_upload.py`) | диагнозы/аллергии из разобранного документа → `merge_onboarding_lists` |
| | агент, тул `save_health_profile` | со слов пациента в диалоге; ставит флаг `health_profile_asked` |
| **Читают** | `core/agent_chat.py::_health_profile_block` | блок «Медпрофиль» в системном промпте (+ курение из `users.smoking_status`) |
| | `core/agent_chat.py::_health_profile_ask_block` | инструкция спросить один раз, если профиль пуст и флага нет |
| | `/meal_context` (`webhook/agent_tools/nutrition.py`) | `constraints` — KB-файл приоритетнее, затем `onboarding_data`; источник в `constraints_source` |
| | `services/doctor_report.py` | «проблемы»/аллергии/лекарства в отчёте для врача |

Курение — отдельная колонка `users.smoking_status` (`never`/`former`/`current`/`occasional`), не в `onboarding_data`. Её читают промпт-блок, дашборд и `/user_profile`.

История: #340 (курение в промпт, fallback `/meal_context`, `save_health_profile`), #7/#309 (сплиттер: запятая не разделитель пунктов).
