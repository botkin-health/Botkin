"""
BotkinClaw — conversational AI-agent для @Botkin_md_bot (in-process handler).

Вызывается из `handlers/text.py` когда LLM router классифицирует сообщение как
`type=other` (т.е. не еда / добавка / АД и т.п. — свободный вопрос). Модуль
оборачивает Anthropic Messages API call с tools, используя:

- per-user system prompt из `users.agent_system_prompt`
- ~14 tools, которые HTTP+JWT-вызывают эндпоинты `webhook/agent_tools_api.py`
- история диалога из таблицы `agent_conversations` (HISTORY_WINDOW последних)

История архитектуры: см. [ADR-0002](docs/architecture/decisions/0002-rejecting-nanoclaw-for-simpler-agent.md)
— почему отказались от NanoClaw, и почему имя BotkinClaw (игра слов: бот сам
играет роль «контейнера» в JWT-контракте).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import jwt as pyjwt
import requests

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings
from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Sonnet 4.6 — рабочая модель агента (откат с Opus 4.8 01.06.2026 по стоимости:
# Opus давал ~$7.5/активный день ≈ $100/мес, дорогие tool-итерации; Sonnet в ~5×
# дешевле при достаточном качестве для семейного медбота). $3/$15 за MT.
MODEL = "claude-sonnet-4-6"
# Fallback на 4.5 если 4.6 вернул 529/503/429. Другой compute pool (обычно
# свободнее). ⚠️ Sonnet 4.5 НЕ поддерживает output_config.effort → в fallback-
# ветке effort снимается (см. _post_with_overload_retry), иначе 400.
FALLBACK_MODEL = "claude-sonnet-4-5"
# effort=medium — документированный sweet spot Sonnet 4.6 для чата: дешевле и
# быстрее дефолтного high, без потери качества на разговорных задачах.
AGENT_EFFORT = "medium"
MAX_TOKENS = 4000  # 2000 обрезал развёрнутые многофакторные ответы (прецедент:
# разбор «алкоголь по всем диагнозам» Димы оборвался на полуслове). 4000 хватает
# на полный разбор с таблицей; короткие ответы лимит не трогает (бот сам краток).
MAX_TOOL_ITERATIONS = 6  # safety net against tool loops
HISTORY_WINDOW = 20  # last N messages from agent_conversations

# Tools API base URL — same container, FastAPI on 8081.
# When running inside healthvault_bot container, this is localhost:8081 directly.
TOOLS_API_BASE = "http://localhost:8081/api/agent"

JWT_TTL_HOURS = 24  # short-lived; agent_chat regenerates per request

# ---------------------------------------------------------------------------
# Tool schema (BotkinClaw tools — wrap webhook/agent_tools_api.py endpoints)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_user_profile",
        "description": "Базовый профиль: имя, возраст, рост, пол, когорта, pack_name. Обычно не нужен — контекст уже в system prompt.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dashboard_summary",
        "description": "ГЛАВНЫЙ tool: сводка здоровья за последние 7 дней — средние шаги, пульс, активные ккал, ккал съеденные, последний вес+%жира. Используй для любых вопросов 'как мои дела/неделя/прогресс'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_meals",
        "description": (
            "Недавние приёмы пищи. days=1..90, по умолчанию 3. "
            "Для поиска по длинному периоду («ел ли я X за месяцы», «как часто пельмени») "
            "ставь большой days и compact=true — вернёт компактно (имена продуктов + калории), "
            "без раздувания контекста. days>14 авто-включает compact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 3},
                "compact": {
                    "type": "boolean",
                    "default": False,
                    "description": "Лёгкий формат (имена продуктов + калории) для поиска по длинному периоду.",
                },
            },
        },
    },
    {
        "name": "list_kb_keys",
        "description": (
            "Список реальных топ-уровневых ключей knowledge_base ЭТОГО пользователя "
            "(у разных людей схемы расходятся: у кого-то `echocardiogram`/`current_medications`, "
            "у кого-то `mrt`/`tumor_markers`, у кого-то `cardio`/`endoscopy`). "
            "ВСЕГДА зови это первым, если юзер спрашивает про специфичный вид обследования "
            "(ЭхоКГ, холтер, МРТ, КТ, операции, текущие препараты, диагнозы) и ты не уверен "
            "под каким именно ключом эти данные лежат. Для каждого ключа возвращает "
            "type (list/dict) и count — видно есть ли там данные или секция пустая."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_kb_value",
        "description": (
            "Значение из knowledge base по ключу (поддерживает dot-notation, например "
            "'blood_tests.0.values.cholesterol'). Распространённые ключи: 'blood_tests', "
            "'hormones', 'vitamins', 'ultrasound', 'ecg', 'echocardiogram', 'holter_ecg', "
            "'current_medications', 'medications', 'chronic_diagnoses', 'diagnoses', "
            "'operations', 'imaging', 'mrt', 'endoscopy', 'cardio'. ВАЖНО: если не уверен "
            "какой именно ключ есть у этого юзера — сначала позови `list_kb_keys`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "get_open_questions",
        "description": (
            "Открытые клинические вопросы и красные флаги пользователя из его KB. "
            "ОБЯЗАТЕЛЬНО зови этот tool в начале ЛЮБОГО медицинского диалога — "
            "разбор анализов, диагнозов, препаратов, симптомов, планирование "
            "обследований. Это «висящие» вопросы которые ждут решения врача или "
            "повторного анализа: пропущенные маркеры, не закрытые followup'ы, "
            "клинические red flags. Прецедент 25.05.2026: папа Александра "
            "спрашивал «какие у меня диагнозы», бот ответил списком из 8 — но "
            "не упомянул что K+/Mg+/ТТГ ни разу не сдавались при QTc 0.60 (это "
            "висело в open_questions). Цель этого tool — чтобы такое не повторялось. "
            "Если в ответе questions=[] и source='not-tracked' — у пользователя "
            "ещё нет ведённого списка, это нормально, просто продолжай. "
            "Когда questions есть — упомяни ХОТЯ БЫ ОДИН релевантный текущему "
            "вопросу пункт в своём ответе, даже если юзер про него не спрашивал. "
            "Не вываливай весь список — отбери 1-3 самых релевантных."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_bp",
        "description": "Измерения артериального давления за последние N дней (1-90, по умолчанию 14). Возвращает каждый замер + статистику: средние систолика/диастолика, max/min, % замеров выше 140/90 (порог гипертонии 1 ст).",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
        },
    },
    {
        "name": "get_recent_sleep",
        "description": (
            "Сон за последние N дней (1-90, по умолчанию 14). Возвращает каждую ночь + средняя "
            "продолжительность, качество, deep/REM минуты, и поле `latest_available_date` — "
            "последняя ночь, по которой ЕСТЬ данные.\n\n"
            "ЕСЛИ за прошедшую ночь данных нет (count=0 или последняя ночь в items не сегодняшняя/"
            "вчерашняя) — НЕ говори расплывчато «подожди 10-15 минут». Скажи честно: назови "
            "`latest_available_date` («последние данные о сне — за DATE»), объясни, что данные с "
            "часов появляются у Garmin с задержкой и подтягиваются автоматически каждые ~30 минут, "
            "и предложи заглянуть позже или прислать `/sync`. Не выдумывай конкретные часы/минуты."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
        },
    },
    {
        "name": "get_recent_supplements",
        "description": (
            "ЕДИНСТВЕННЫЙ источник для вопросов 'какие витамины/добавки я "
            "принимаю', 'сколько раз в неделю пил магний', 'когда последний "
            "раз принимал креатин', 'насколько я придерживаюсь схемы'. "
            "Возвращает агрегацию по каждой добавке за период: days_taken, "
            "total_intakes (несколько раз в день — норма), adherence_pct "
            "(% дней приёма от периода), last_date, last_dosage. "
            "Период по умолчанию 30 дней. НЕ используй контекст из system "
            "prompt — там может быть устаревший список, реальный лог здесь."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 30}},
        },
    },
    {
        "name": "get_recent_biomarkers",
        "description": (
            "ЕДИНСТВЕННЫЙ источник для вопросов про анализы крови, гормоны, "
            "витамины, биомаркеры. Возвращает строки blood_tests из Postgres: "
            "дата + тип + values (dict со значениями маркеров типа vitamin_d, "
            "LDL, HDL, glucose, HbA1c, testosterone, TSH, ferritin, ApoB и т.п.). "
            "Используй ВСЕГДА когда юзер спрашивает про любые лабораторные показатели: "
            "'какой у меня витамин Д', 'как менялся холестерин', 'какие гормоны сдавал', "
            "'покажи динамику ЛПНП', 'какие анализы за последний год'. "
            "limit по умолчанию 20 (история на год), увеличь до 50 для 'всё что есть'. "
            "НЕ ИСПОЛЬЗУЙ get_kb_value для анализов — оно ничего не вернёт."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        },
    },
    {
        "name": "get_phenoage",
        "description": (
            "Биологический возраст по формуле Levine 2018 (Aging Cell). "
            "Возвращает bio_age, chronological_age, delta_years, и 9 маркеров "
            "(albumin, creatinine, glucose, hs_CRP, lymphocytes, MCV, RDW, ALP, WBC) "
            "с пометкой 'younger'/'older' vs NHANES median. Используй для "
            "вопросов 'какой мой биологический возраст', 'PhenoAge', "
            "'на сколько я моложе/старше паспорта', 'состав панели биовозраста'. "
            "Если каких-то маркеров не хватает — вернёт error со списком."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_workouts",
        "description": (
            "Анализ тренировок по канонам Seiler 80/20 / Attia Z2 / норвежский 4x4. "
            "Возвращает: by_type (счётчик по Garmin type — running, walking, "
            "strength_training, yoga и т.п.), Z2 min/week, HIIT min/week, A:C "
            "load ratio (sweet spot 0.8-1.3), polarized distribution Z1+Z2/Z3/Z4+Z5 %, "
            "extremes_by_type (рекорды на каждый тип — longest_by_duration и "
            "longest_by_distance, считаются по ВСЕМ тренировкам в окне), "
            "список последних 15 тренировок с type+name+distance_km+duration_min. "
            "Используй для 'сколько раз я бегал', 'сколько Z2 в неделю', "
            "'каков мой A:C ratio', 'правильное ли распределение зон'. "
            "Для вопросов 'самая длинная пробежка / самая дальняя пробежка' — "
            "ВСЕГДА смотри в extremes_by_type[бег|ходьба|...].longest_by_distance "
            "(или longest_by_duration), НЕ в items[] — items обрезан до 15 свежих "
            "и редкие длинные сессии туда не попадают. "
            "ВАЖНО: для классификации (бег/ходьба/силовая) ВСЕГДА смотри поле "
            "`type` (Garmin classification), а НЕ `name` (user-set route label "
            "типа 'Москва - База' который может быть бегом ИЛИ ходьбой). "
            "Используй by_type для прямых вопросов типа 'сколько раз я бегал'. "
            "По умолчанию days=30; для вопросов 'за год' / 'в этом году' "
            "ставь days=180 (максимум). "
            "Multi-user: owner-cohort использует file-source (rich data со Z2/zones/load), "
            "остальные пользователи — DB-fallback (только базовые поля type/duration/distance), "
            "поле `source` в ответе показывает откуда взялись данные."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 30}},
        },
    },
    {
        "name": "get_recent_trends",
        "description": (
            "Per-day тренды HRV, Body Battery, Stress, Steps, RHR, Sleep + "
            "флаг alcohol (был ли в этот день алкоголь, из nutrition_log) "
            "за N дней (по умолчанию 14, до 180). В отличие от get_dashboard_summary "
            "который даёт только AVG за 7 дней — тут видно динамику ДЕНЬ ЗА ДНЁМ. "
            "Используй для 'падает ли мой HRV', 'когда у меня был стресс', "
            "'какой у меня body battery утром', 'как менялся пульс покоя', "
            "а также для корреляций 'алкоголь → HRV/стресс следующего дня'. "
            "Возвращает items (per-day, поле alcohol:bool) + stats (avg/min/max + alcohol_days). "
            "Для КОРРЕЛЯЦИЙ и ГРАФИКОВ на длинном окне ставь full_series=true "
            "(вернёт ВСЕ точки окна, а не последние 30) и days=90..180."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 14},
                "full_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Вернуть все точки окна (для корреляций/графиков). Дефолт false (последние 30).",
                },
            },
        },
    },
    {
        "name": "get_weight_history",
        "description": (
            "История веса и состава тела (жир %, мышечная масса, висцеральный жир, BMI). "
            "Источник — таблица `weights` (с 2015 у долгих пользователей). "
            "Возвращает: latest (текущий замер), all_time (рекорды за всю историю — "
            "min/max веса и жира с датами), и опционально in_window (рекорды в окне days). "
            "Используй для вопросов 'самый низкий жир за всё время', 'минимальный вес', "
            "'как изменился жир за полгода', 'когда был в лучшей форме'. "
            "\n\n"
            "Параметр `series=true` ДОБАВЛЯЕТ поле `points` с массивом всех "
            "ежедневных замеров {date, weight_kg, body_fat_pct} в окне. "
            "Используй когда собираешься рисовать график (render_chart / "
            "render_report). БЕЗ series ответ короткий — это нормально для "
            "текстовых вопросов."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 7,
                    "maximum": 365,
                    "description": "Окно в днях. Без параметра — only all_time.",
                },
                "series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Вернуть все точки в `points` для рисования графика. Дефолт false.",
                },
            },
        },
    },
    {
        "name": "get_body_measurements",
        "description": (
            "Антропометрия: талия, шея, бёдра, грудь, бедро, бицепс (см). "
            "Источник — ручной ввод. Возвращает latest, extremes (min/max) "
            "по каждой метрике, и тренд талии (waist) за последние 6 замеров. "
            "Используй для 'какая у меня талия сейчас', 'как изменилась талия за полгода', "
            "'сравни мою фигуру до и после'. Талия — главная метрика метаболического "
            "здоровья (важнее BMI для ССЗ-риска)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_user_settings",
        "description": (
            "Настройки и цели пользователя: target_weight_kg + date (цель веса), "
            "supplements_regimen (JSONB список ежедневных добавок с дозами и слотами "
            "morning_with/evening), calorie_goal_pct (дефицит/профицит), BMR-источник, "
            "reminders (напоминания о добавках), profile (sex/height/birth_date/timezone). "
            "Используй для 'какие у меня цели', 'что я регулярно принимаю', 'какой "
            "дефицит', 'когда напоминания'. Полезно сверять `supplements_log` (что "
            "реально принял) против `supplements_regimen` (что планировал)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_profile_questionnaire",
        "description": (
            "Анкета пользователя из users table: sex, height_cm, birth_date (+ возраст), "
            "timezone, smoking_status (never/former/current/occasional), kb_status "
            "(приватность knowledge_base: shared = доступно AI, private = только юзеру), "
            "garmin_connected, pack_name, превью agent_system_prompt (500 симв). "
            "Используй для 'что я указывал в анкете', 'мои настройки приватности', "
            "'подключён ли Garmin', 'какой у меня возраст в системе'. "
            "Также вызывай ПЕРЕД update_profile_questionnaire чтобы показать что меняется."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_profile_questionnaire",
        "description": (
            "Изменить анкетные поля в users table. Все поля опциональны — обновятся "
            "только переданные. ПЕРЕД использованием — обязательно подтверди с юзером "
            "что именно меняешь (особенно agent_system_prompt — длинная строка, влияет "
            "на поведение агента). Допустимые значения: smoking_status ∈ "
            "{never,former,current,occasional}, kb_status ∈ {shared,private}, sex ∈ "
            "{male,female,other}, birth_date YYYY-MM-DD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sex": {"type": "string", "enum": ["male", "female", "other"]},
                "height_cm": {"type": "integer", "minimum": 100, "maximum": 250},
                "birth_date": {"type": "string", "description": "YYYY-MM-DD"},
                "timezone": {"type": "string"},
                "smoking_status": {"type": "string", "enum": ["never", "former", "current", "occasional"]},
                "kb_status": {"type": "string", "enum": ["shared", "private"]},
                "pack_name": {"type": "string"},
                "agent_system_prompt": {
                    "type": "string",
                    "description": "Полная замена промпта. Длинная (5-10К). Опасное поле.",
                },
            },
        },
    },
    {
        "name": "update_user_settings",
        "description": (
            "Изменить настройки в user_settings table: target_weight_kg + target_weight_date "
            "(цель веса), calorie_goal_pct (-15 = дефицит 15%), bmr_override/bmr_source, "
            "supplements (ПОЛНАЯ замена списка добавок — каждая {name, dose?, slot?}, slots: "
            "morning_before / morning_with / evening), reminders. Все поля опциональны. "
            "ВАЖНО: чтобы добавить ОДНУ добавку — сначала get_user_settings, модифицируй "
            "список локально, потом update с полным новым списком. ПЕРЕД изменением — "
            "подтверди с юзером."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_weight_kg": {"type": "number", "minimum": 30, "maximum": 300},
                "target_weight_date": {"type": "string", "description": "YYYY-MM-DD"},
                "calorie_goal_pct": {"type": "integer", "minimum": -50, "maximum": 50},
                "bmr_override": {"type": "integer", "minimum": 500, "maximum": 5000},
                "bmr_source": {"type": "string", "enum": ["auto", "override", "fixed"]},
                "supplement_reminders_enabled": {"type": "boolean"},
                "supplement_reminder_time": {"type": "string", "description": "HH:MM"},
                "show_calorie_budget_bar": {"type": "boolean"},
                "supplements": {
                    "type": "array",
                    "description": "Полный новый список добавок (заменяет все).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "dose": {"type": "string"},
                            "slot": {"type": "string", "enum": ["morning_before", "morning_with", "evening"]},
                        },
                        "required": ["name"],
                    },
                },
            },
        },
    },
    {
        "name": "get_indoor_air",
        "description": (
            "Воздух дома: CO2 ppm, температура, влажность, шум. Источник — Netatmo "
            "Healthy Home Coach. Только для owner-cohort (Alex). Возвращает latest "
            "(текущий замер) + history по комнатам (агрегаты за N дней). "
            "Используй для 'CO2 в спальне', 'духота', 'температура дома'. "
            "Норма CO2 < 1000 ppm, >1400 — критично для сна/концентрации."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 60, "default": 7}},
        },
    },
    {
        "name": "get_outdoor_weather",
        "description": (
            "Погода снаружи (Open-Meteo, Москва): температура max/min/средняя, "
            "давление, влажность, UV, осадки, словесное описание. Без параметра — "
            "последний день; с date='YYYY-MM-DD' — конкретный. Используй для "
            "'какая погода сегодня', 'давление', 'был ли дождь', анализа корреляций "
            "(например 'влияет ли давление на пульс покоя')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD (optional)"}},
        },
    },
    {
        "name": "get_day_summary",
        "description": (
            "Точечная сводка за конкретный день (date='YYYY-MM-DD'): ккал/БЖУ, был ли "
            "воркаут, часов сна, вес, АД. Источник — таблица daily_summaries (агрегаты "
            "от ночного sync). В отличие от get_dashboard_summary который даёт AVG за 7 дней, "
            "тут конкретный день. Используй для 'что у меня было 14 марта', 'сравни этот "
            "понедельник с прошлым'. Если данных за день нет — вернёт no_data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "log_meal_text",
        "description": (
            "Залогировать приём пищи из текстового описания. ИСПОЛЬЗОВАТЬ ТОЛЬКО "
            "если юзер ЯВНО просит 'запиши' или 'залогируй'. Не пытайся логировать "
            "каждое упоминание еды.\n\n"
            "Если юзер указал ДЕНЬ приёма («вчера», «позавчера», «29 мая», «в "
            "понедельник») — вычисли конкретную дату и передай её в `date` "
            "(YYYY-MM-DD), опираясь на сегодняшнее число. Без указания дня `date` "
            "НЕ передавай (запишется на сегодня). После записи ОБЯЗАТЕЛЬНО назови "
            "дату в ответе, если она не сегодняшняя («записал на 29 мая»)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "date": {
                    "type": "string",
                    "description": "Дата приёма YYYY-MM-DD. Только если юзер указал день; иначе не передавать (=сегодня).",
                },
                "slot": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "edit_meal",
        "description": (
            "Изменить УЖЕ залогированный приём пищи: перенести на другой день (new_date), "
            "сменить слот/время (new_slot), переименовать (new_name). "
            "meal_id бери из get_recent_meals (поле id). "
            "ИСПОЛЬЗОВАТЬ когда юзер просит «перенеси/исправь/измени/это был не обед а ужин» "
            "про уже записанную еду. Передавай только те поля, что меняются."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {"type": "integer", "description": "id записи из get_recent_meals"},
                "new_date": {"type": "string", "description": "Новая дата YYYY-MM-DD (перенос на другой день)"},
                "new_slot": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]},
                "new_name": {"type": "string", "description": "Новое название приёма"},
            },
            "required": ["meal_id"],
        },
    },
    {
        "name": "delete_meal",
        "description": (
            "Удалить залогированный приём пищи по meal_id (из get_recent_meals, поле id). "
            "ИСПОЛЬЗОВАТЬ когда юзер просит «удали/убери» запись о еде. "
            "Если нужно перенести на другой день — используй edit_meal с new_date, не delete+log."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"meal_id": {"type": "integer", "description": "id записи из get_recent_meals"}},
            "required": ["meal_id"],
        },
    },
    {
        "name": "log_bp",
        "description": "Залогировать измерение давления.",
        "input_schema": {
            "type": "object",
            "properties": {
                "systolic": {"type": "integer"},
                "diastolic": {"type": "integer"},
                "pulse": {"type": "integer"},
            },
            "required": ["systolic", "diastolic"],
        },
    },
    {
        "name": "log_supplement",
        "description": "Залогировать приём добавки/витамина.",
        "input_schema": {
            "type": "object",
            "properties": {
                "supplement_name": {"type": "string"},
                "dosage": {"type": "string"},
            },
            "required": ["supplement_name"],
        },
    },
    {
        "name": "render_chart",
        "description": (
            "Универсальный рендер графика через QuickChart → Telegram. Для всего что "
            "не покрывает render_report (тот быстрее для типовых случаев).\n\n"
            "КОГДА: «нарисуй», «график», «инфографика», «сравни X и Y», «корреляция».\n\n"
            "ФОРМАТ spec — Chart.js v4. Пиши МИНИМАЛЬНО, только данные и тип; "
            "стиль (цвета, шрифты, легенду, сетку, размеры) сервер ставит сам "
            "из Botkin-палитры. НЕ заполняй borderColor / backgroundColor / "
            "tension / pointRadius — сервер заполнит. Заполняй ТОЛЬКО:\n"
            "  • type ('line'|'bar'|'scatter'|'doughnut'|'pie'|'radar'|'polarArea')\n"
            "  • data.labels, data.datasets[].label, data.datasets[].data\n"
            "  • options.plugins.title.text — заголовок графика (обязательно)\n"
            "  • options.scales — только если нужны нестандартные оси (multi-axis: yAxisID на datasets + scales.y/y1)\n\n"
            "Минимальный пример:\n"
            "{type:'line', data:{labels:['янв','фев','мар'], datasets:[{label:'Вес', data:[82,81,80]}]}, "
            "options:{plugins:{title:{text:'Вес за квартал'}}}}\n\n"
            "Кириллица в labels/title работает нормально. После render — короткий "
            "комментарий (1-3 предложения), не пересказывай содержимое картинки."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart": {
                    "type": "object",
                    "description": "Chart.js v4 config: {type, data, options}",
                },
                "caption": {
                    "type": "string",
                    "description": "Подпись под фото в Telegram (1 строка, без markdown).",
                },
                "width": {"type": "integer", "default": 600, "minimum": 200, "maximum": 1600},
                "height": {"type": "integer", "default": 400, "minimum": 200, "maximum": 1200},
            },
            "required": ["chart"],
        },
    },
    {
        "name": "render_report",
        "description": (
            "Сгенерировать и ОТПРАВИТЬ юзеру в Telegram PNG-инфографику. "
            "Tool сам делает sendPhoto — тебе НЕ надо ничего возвращать в тексте, "
            "Telegram уже получил картинку к моменту когда ты увидишь результат. "
            "После использования напиши КОРОТКИЙ комментарий-резюме к картинке "
            "(2-4 предложения), не пытайся пересказать всё что на ней. "
            "\n\n"
            "КОГДА ИСПОЛЬЗОВАТЬ: ВМЕСТО рисования markdown-таблицы с динамикой "
            "лабораторных значений. Триггеры: «динамика анализов», «разбери "
            "анализы», «график X», «нарисуй», «как менялся X», «покажи отчёт», "
            "«инфографика», «сделай разбор для врача». "
            "\n\n"
            "Два режима:\n"
            "  • report_type='biomarker_dynamics' (DEFAULT) — общая панель 2×3 "
            "    с 6 ключевыми маркерами (липиды + метаболизм + печень и т.п.). "
            "    Зови когда юзер просит общую картину / разбор / для врача.\n"
            "  • report_type='single_biomarker' + marker='<имя>' — большой график "
            "    одного маркера. Зови когда юзер спрашивает про конкретный "
            "    показатель: «график витамина Д», «как менялся ЛПНП», «динамика "
            "    глюкозы». Параметр marker принимает русские названия (витамин Д, "
            "    глюкоза, ЛПНП, холестерин, гликированный, ферритин, тестостерон) "
            "    и латинские (LDL, HDL, HbA1c, ALT, TSH, vitamin_d, и т.п.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["biomarker_dynamics", "single_biomarker"],
                    "default": "biomarker_dynamics",
                },
                "marker": {
                    "type": "string",
                    "description": ("Имя биомаркера для режима single_biomarker. Игнорируется для biomarker_dynamics."),
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# JWT generation (matches webhook/jwt_auth.py contract)
# ---------------------------------------------------------------------------


def agent_id_for(user: User) -> str:
    """Deterministic agent identifier embedded in JWT payload.

    BotkinClaw (in-process agent) — бот сам играет роль "контейнера", отдельных
    per-user контейнеров не существует. Если `users.container_id` уже выставлен
    (исторические значения вроде `in-process-andrey`) — используем его;
    иначе деривируем из telegram_id. И generate_jwt, и validate_jwt используют
    эту же функцию, поэтому подпись всегда сходится с проверкой.

    Legacy: до удаления NanoClaw (см. ADR-0002) `container_id` указывал на
    реальный onecli-контейнер. После выпила NanoClaw поле осталось как
    rudiment — может быть пустым для новых пользователей.
    """
    return user.container_id or f"botkinclaw-{user.telegram_id}"


def _generate_jwt(user: User) -> str:
    """Short-lived JWT для BotkinClaw tool calls."""
    if not user.jwt_secret:
        raise RuntimeError(f"User {user.telegram_id} missing jwt_secret; cannot generate agent JWT")
    payload = {
        "user_id": user.telegram_id,
        "container_id": agent_id_for(user),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, user.jwt_secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _call_tool(name: str, args: dict, token: str) -> str:
    """Synchronous HTTP call to tools API. Returns raw response body as string."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        if name == "get_user_profile":
            r = requests.get(f"{TOOLS_API_BASE}/user_profile", headers=headers, timeout=10)
        elif name == "get_dashboard_summary":
            r = requests.get(f"{TOOLS_API_BASE}/dashboard_summary", headers=headers, timeout=15)
        elif name == "get_recent_meals":
            days = int(args.get("days", 3))
            params = {"days": days}
            if args.get("compact"):
                params["compact"] = "true"
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_meals",
                params=params,
                headers=headers,
                timeout=15,
            )
        elif name == "list_kb_keys":
            r = requests.get(
                f"{TOOLS_API_BASE}/list_kb_keys",
                headers=headers,
                timeout=10,
            )
        elif name == "get_kb_value":
            r = requests.get(
                f"{TOOLS_API_BASE}/kb_value",
                params={"key": args["key"]},
                headers=headers,
                timeout=10,
            )
        elif name == "get_open_questions":
            r = requests.get(
                f"{TOOLS_API_BASE}/open_questions",
                headers=headers,
                timeout=10,
            )
        elif name == "get_recent_bp":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_bp",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_sleep":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_sleep",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_supplements":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_supplements",
                params={"days": int(args.get("days", 30))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_biomarkers":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_biomarkers",
                params={"limit": int(args.get("limit", 20))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_phenoage":
            r = requests.get(f"{TOOLS_API_BASE}/phenoage", headers=headers, timeout=15)
        elif name == "get_recent_workouts":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_workouts",
                params={"days": int(args.get("days", 30))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_trends":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_trends",
                params={
                    "days": int(args.get("days", 14)),
                    "full_series": bool(args.get("full_series", False)),
                },
                headers=headers,
                timeout=20,
            )
        elif name == "get_weight_history":
            params: dict[str, Any] = {}
            if "days" in args and args["days"] is not None:
                params["days"] = int(args["days"])
            if args.get("series"):
                params["series"] = "true"
            r = requests.get(
                f"{TOOLS_API_BASE}/weight_history",
                params=params,
                headers=headers,
                timeout=15,
            )
        elif name == "get_body_measurements":
            r = requests.get(f"{TOOLS_API_BASE}/body_measurements", headers=headers, timeout=15)
        elif name == "get_user_settings":
            r = requests.get(f"{TOOLS_API_BASE}/user_settings", headers=headers, timeout=10)
        elif name == "get_profile_questionnaire":
            r = requests.get(f"{TOOLS_API_BASE}/profile_questionnaire", headers=headers, timeout=10)
        elif name == "update_profile_questionnaire":
            r = requests.post(
                f"{TOOLS_API_BASE}/update_profile_questionnaire",
                json=args,
                headers=headers,
                timeout=15,
            )
        elif name == "update_user_settings":
            r = requests.post(
                f"{TOOLS_API_BASE}/update_user_settings",
                json=args,
                headers=headers,
                timeout=15,
            )
        elif name == "get_indoor_air":
            r = requests.get(
                f"{TOOLS_API_BASE}/indoor_air",
                params={"days": int(args.get("days", 7))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_outdoor_weather":
            weather_params: dict[str, Any] = {}
            if args.get("date"):
                weather_params["date"] = args["date"]
            r = requests.get(
                f"{TOOLS_API_BASE}/outdoor_weather",
                params=weather_params,
                headers=headers,
                timeout=10,
            )
        elif name == "get_day_summary":
            r = requests.get(
                f"{TOOLS_API_BASE}/day_summary",
                params={"date": args["date"]},
                headers=headers,
                timeout=10,
            )
        elif name == "log_meal_text":
            r = requests.post(f"{TOOLS_API_BASE}/log_meal_text", json=args, headers=headers, timeout=30)
        elif name == "edit_meal":
            r = requests.post(f"{TOOLS_API_BASE}/edit_meal", json=args, headers=headers, timeout=10)
        elif name == "delete_meal":
            r = requests.post(f"{TOOLS_API_BASE}/delete_meal", json=args, headers=headers, timeout=10)
        elif name == "log_bp":
            r = requests.post(f"{TOOLS_API_BASE}/log_bp", json=args, headers=headers, timeout=10)
        elif name == "log_supplement":
            r = requests.post(f"{TOOLS_API_BASE}/log_supplement", json=args, headers=headers, timeout=10)
        elif name == "render_report":
            # Side-effect tool — генерит PNG и шлёт юзеру sendPhoto.
            # Возвращает только статус (не саму картинку), чтобы агент
            # дальше отвечал коротким текстом-комментарием к картинке.
            payload = {"report_type": args.get("report_type", "biomarker_dynamics")}
            if "marker" in args:
                payload["marker"] = args["marker"]
            r = requests.post(
                f"{TOOLS_API_BASE}/render_report",
                json=payload,
                headers=headers,
                timeout=30,
            )
        elif name == "render_chart":
            # Универсальный рендер через QuickChart.io. Side-effect — sendPhoto.
            r = requests.post(
                f"{TOOLS_API_BASE}/render_chart",
                json={
                    "chart": args.get("chart") or {},
                    "caption": args.get("caption"),
                    "width": args.get("width", 600),
                    "height": args.get("height", 400),
                },
                headers=headers,
                timeout=30,
            )
        else:
            return json.dumps({"error": f"unknown tool: {name}"})

        if not r.ok:
            return json.dumps({"error": f"HTTP {r.status_code}", "body": r.text[:500]})
        return r.text
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Conversation history (Postgres)
# ---------------------------------------------------------------------------


TOOL_RESULT_TRUNCATE_CHARS = 1500
"""Cap on tool_result content length kept in HISTORY between turns.

Current turn always sees full tool_result (router builds it fresh).
But prior turns' tool_results bloat input_tokens — get_recent_biomarkers
can return 10KB JSON. After this turn, the agent's text answer summarised
what it needed; further turns can work from the summary + truncated tail.

1500 chars ≈ ~400 tokens. Keeps enough context (first table, a few rows)
without re-paying for full payload.
"""


def _truncate_tool_results_in_history(messages: list[dict]) -> list[dict]:
    """Shrink tool_result blocks in the historical messages.

    Only mutates blocks of type='tool_result'. The current turn's
    tool_result hasn't been appended yet by callers — it's safe.
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            body = block.get("content")
            if isinstance(body, str) and len(body) > TOOL_RESULT_TRUNCATE_CHARS:
                block["content"] = body[:TOOL_RESULT_TRUNCATE_CHARS] + f"\n…[truncated, was {len(body)} chars]"
    return messages


def _load_history(db, user_id: int, limit: int = HISTORY_WINDOW) -> list[dict]:
    """Load last N messages from agent_conversations in chronological order.

    Returns list shaped for Anthropic API `messages` parameter.
    Each row's `content` is already a JSONB list of content blocks.
    Adjacent rows of same role are squashed by Anthropic-side; we don't.
    """
    from sqlalchemy import text

    # Фильтр source: NULL = легаси (до миграции add_agent_review_consent) или
    # реальный ход BotkinClaw. 'botkinclaw' = новые ходы агента. Любой
    # 'router_*' (raw-текст из food/vitamins/BP ветки) — не часть диалога с
    # Claude, в историю не подмешиваем, чтобы агент не пытался отвечать на
    # пищевые сообщения.
    sql = text(
        """
        SELECT role, content
        FROM agent_conversations
        WHERE user_id = :uid AND (source IS NULL OR source = 'botkinclaw')
        ORDER BY id DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"uid": user_id, "lim": limit}).fetchall()
    rows = list(reversed(rows))  # chronological
    # Map our role values → Anthropic roles.
    # We store 'user' / 'assistant' (verbatim from API) and intermediary
    # 'tool_use' / 'tool_result' are part of assistant / user messages
    # respectively, but in our denormalised storage they're separate rows.
    # We re-group adjacent tool_use/tool_result rows back into assistant/user
    # turns.
    messages: list[dict] = []
    for role, content in rows:
        if role == "user":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})
        elif role == "tool_use":
            # tool_use blocks are part of an assistant message — append.
            if messages and messages[-1]["role"] == "assistant":
                if isinstance(messages[-1]["content"], str):
                    messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}]
                messages[-1]["content"].extend(content)
            else:
                messages.append({"role": "assistant", "content": content})
        elif role == "tool_result":
            # tool_result blocks belong to a user message.
            if messages and messages[-1]["role"] == "user":
                if isinstance(messages[-1]["content"], str):
                    messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}]
                messages[-1]["content"].extend(content)
            else:
                messages.append({"role": "user", "content": content})

    # Truncate large tool_results in history to save input tokens on each call
    messages = _truncate_tool_results_in_history(messages)
    return _validate_history(messages)


def _validate_history(messages: list[dict]) -> list[dict]:
    """Strip orphan tool_use/tool_result blocks that violate Anthropic API.

    Bug fix for 400 'unexpected tool_use_id in tool_result blocks'. Reasons
    orphans happen at HISTORY_WINDOW boundary, after row deletions, or after
    save crashes between tool_use save and matching tool_result save.

    Algorithm:
      1. Collect all tool_use_id present anywhere in the window
      2. Drop any tool_result blocks whose tool_use_id isn't in that set
      3. Drop any tool_use blocks whose id isn't matched by a later tool_result
      4. Drop messages that become empty after block-stripping
      5. Strip leading message if its only content was orphan tool blocks
         (Anthropic requires first message to be 'user' with real text)
    """
    # First pass: collect all tool_use_id and tool_result tool_use_id present
    tool_use_ids: set[str] = set()
    tool_result_ids: set[str] = set()
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                if tid := block.get("id"):
                    tool_use_ids.add(tid)
            elif block.get("type") == "tool_result":
                if tid := block.get("tool_use_id"):
                    tool_result_ids.add(tid)

    # Both must match — orphans on either side are stripped
    valid_ids = tool_use_ids & tool_result_ids

    # Second pass: strip blocks with id not in valid_ids
    cleaned: list[dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            cleaned.append(m)
            continue
        if not isinstance(content, list):
            cleaned.append(m)
            continue
        new_blocks = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "tool_use":
                    if block.get("id") in valid_ids:
                        new_blocks.append(block)
                    continue
                if btype == "tool_result":
                    if block.get("tool_use_id") in valid_ids:
                        new_blocks.append(block)
                    continue
            new_blocks.append(block)
        if new_blocks:
            cleaned.append({"role": m["role"], "content": new_blocks})

    # Anthropic requires first message role == "user". If we somehow end up
    # with an assistant-first list (because user msg got fully orphaned),
    # drop leading assistants.
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


def _save_message(
    db,
    user_id: int,
    role: str,
    content: Any,
    tool_use_id: Optional[str] = None,
    source: str = "botkinclaw",
):
    """source='e2e_test' для тестовых сообщений с маркером 🧪 (task #62) —
    позволяет потом массово удалять через /admin/cleanup_e2e без риска
    задеть реальные диалоги."""
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO agent_conversations (user_id, role, content, tool_use_id, source)
            VALUES (:uid, :role, CAST(:content AS JSONB), :tid, :src)
            """
        ),
        {
            "uid": user_id,
            "role": role,
            "content": json.dumps(content),
            "tid": tool_use_id,
            "src": source,
        },
    )


def log_router_raw_text(user_id: int, raw_text: str, msg_type: str) -> None:
    """Логирует raw текст сообщения, ушедшего НЕ в BotkinClaw, а в роутер
    (food / vitamins / bp / weight / mixed / body_measurements).

    Цель: чтобы product-review мог увидеть формулировки пользователя даже
    когда сообщение распарсилось в структурку и положилось в спец-таблицу.
    Эти строки не подмешиваются в историю BotkinClaw (см. _load_history).

    Безопасно: ловит и логирует любую ошибку, чтобы не сломать основной
    хэндлер из-за проблемы с записью.
    """
    if not raw_text:
        return
    try:
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(
                text(
                    """
                    INSERT INTO agent_conversations (user_id, role, content, source)
                    VALUES (:uid, 'user', CAST(:content AS JSONB), :src)
                    """
                ),
                {
                    "uid": user_id,
                    "content": json.dumps([{"type": "text", "text": raw_text}]),
                    "src": f"router_{msg_type}",
                },
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"log_router_raw_text failed for {user_id}: {e}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


# Маппинг tool name → короткая фраза для прогресс-индикатора (UI бот'a).
# Идея: пользователь видит «🎨 рисую график...» вместо 18-секундной тишины.
# Если tool здесь нет — фоллбэк на просто «📡 запрос данных».
_TOOL_PROGRESS_LABEL = {
    # Read tools
    "get_recent_meals": "🍽 собираю питание",
    "get_recent_supplements": "💊 смотрю добавки",
    "get_recent_bp": "🩸 поднимаю давление",
    "get_recent_sleep": "😴 проверяю сон",
    "get_recent_trends": "📊 собираю динамику",
    "get_recent_workouts": "🏃 поднимаю тренировки",
    "get_recent_biomarkers": "🧪 смотрю анализы",
    "get_kb_value": "📋 ищу в карте здоровья",
    "list_kb_keys": "🗂 смотрю что есть в карте",
    "get_open_questions": "🚩 свеяю с открытыми вопросами",
    "get_weight_history": "⚖️ собираю историю веса",
    "get_body_measurements": "📏 проверяю замеры",
    "get_dashboard_summary": "📊 свожу метрики",
    "get_user_profile": "👤 читаю профиль",
    "get_user_settings": "⚙️ читаю настройки",
    "get_indoor_air": "🏠 проверяю воздух",
    "get_outdoor_weather": "🌤 смотрю погоду",
    "get_phenoage": "🧬 считаю PhenoAge",
    "get_day_summary": "📅 свожу день",
    "get_profile_questionnaire": "📝 читаю анкету",
    # Write tools
    "log_meal_text": "✍️ записываю еду",
    "edit_meal": "✏️ правлю запись о еде",
    "delete_meal": "🗑 удаляю запись о еде",
    "log_supplement": "✍️ отмечаю добавку",
    "log_bp": "✍️ записываю давление",
    "regenerate_health_token": "🔑 пересоздаю токен",
    "update_profile_questionnaire": "📝 обновляю анкету",
    "update_user_settings": "⚙️ обновляю настройки",
    # Render tools
    "render_report": "🎨 рисую график",
    "render_chart": "🎨 рисую график",
}


def ask_agent(
    user_id: int,
    user_text: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    is_e2e: bool = False,
) -> str:
    """Synchronous — call from `run_in_executor`.

    Returns assistant's text reply. Empty string if nothing produced.
    Errors are raised; caller (handler) catches and replies "технически не вышло".

    is_e2e=True → все _save_message в agent_conversations помечаются
    source='e2e_test' (вместо 'botkinclaw') чтобы потом удалять через
    /admin/cleanup_e2e без риска задеть реальные диалоги. Task #62.
    """
    src = "e2e_test" if is_e2e else "botkinclaw"
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=user_id).first()
        if not user or not user.is_active:
            raise RuntimeError(f"User {user_id} not found or inactive")
        if not user.agent_system_prompt:
            raise RuntimeError(
                f"User {user_id} has no agent_system_prompt — conversational agent not enabled for this user yet"
            )

        token = _generate_jwt(user)

        # Прогресс «думаю» сразу после провижна — пользователь видит что бот
        # начал работать ещё ДО первого Claude-вызова (~3-5 сек).
        if progress_cb:
            try:
                progress_cb("🤔 думаю")
            except Exception:
                logger.exception("progress_cb start failed")

        # Build messages: history + new user turn
        history = _load_history(db, user_id)
        history.append({"role": "user", "content": user_text})

        # Persist user turn immediately so a crash mid-call doesn't lose it.
        _save_message(db, user_id, "user", user_text, source=src)
        db.commit()

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        # Universal meta-directive: prepended to every per-user system prompt.
        # Закрывает повторяющийся класс ошибок — бот корректно отвечает на
        # вопрос пользователя, но НЕ всплывает открытые клинические вопросы
        # из его KB. Прецедент 25.05.2026: папа Александра спрашивал «какие
        # диагнозы» — бот ответил 8 пунктами из KB, но не упомянул что K/Mg/ТТГ
        # ни разу не сдавались при QTc 0.60 (это давно в open_questions).
        # После этой директивы — модель всегда дёргает get_open_questions
        # на любой мед-теме и интегрирует релевантное в ответ.
        UNIVERSAL_META_PROMPT = (
            "# 🩺 ДАННЫЕ АД — ОБЯЗАТЕЛЬНО ЧЕРЕЗ ИНСТРУМЕНТ (универсальный)\n"
            "\n"
            "При ЛЮБОМ вопросе про артериальное давление, его динамику, замеры за\n"
            "день/неделю/период — ВСЕГДА сначала вызови инструмент `recent_bp`.\n"
            "\n"
            "❌ ЗАПРЕЩЕНО:\n"
            "- Говорить «замеров нет» или «не вижу измерений» без вызова recent_bp\n"
            "- Опираться только на историю переписки для суждений о наличии/отсутствии замеров АД\n"
            "\n"
            "Причина: замеры АД поступают напрямую через быстрый regex-обработчик и\n"
            "могут не отражаться в истории чата как обычные сообщения. Инструмент\n"
            "recent_bp всегда показывает актуальную картину из БД.\n"
            "\n"
            "Прецедент 26.05.2026: пользователь сделал 5 замеров (все ✅ Записано),\n"
            "агент ответил «сегодняшних нет» — не вызвал recent_bp, доверился памяти.\n"
            "\n"
            "---\n"
            "\n"
            "# 📲 ИСТОЧНИКИ ДАННЫХ — НЕ ОТРИЦАЙ ПОДДЕРЖКУ (универсальный)\n"
            "\n"
            "Если пользователь спрашивает, как подключить данные/устройство — НЕ говори, что\n"
            "источник «не поддерживается» или «интеграции нет».\n"
            "- Apple Health (Apple Watch, тонометры/весы, пишущие в Apple Health) ПОДДЕРЖИВАЕТСЯ:\n"
            "  через приложение Health Auto Export ИЛИ бесплатно через iOS Shortcuts. Персональный\n"
            "  ключ выдаёт команда `/health_token` — направляй пользователя туда.\n"
            "- Garmin и Whoop тоже поддерживаются (свои интеграции); вес/давление/еду можно вводить\n"
            "  вручную в чат (текст/фото/голос).\n"
            "Никогда не утверждай, что у Botkin нет интеграции с Apple Health / HealthKit.\n"
            "\n"
            "---\n"
            "\n"
            "# ⚠️ ПРОТОКОЛ ОТВЕТА НА МЕДИЦИНСКИЙ ВОПРОС (универсальный)\n"
            "\n"
            "При ЛЮБОМ вопросе пользователя который касается:\n"
            "- разбора анализов / биомаркеров / гормонов\n"
            "- его диагнозов / препаратов / терапии\n"
            "- симптомов / самочувствия / эпизодов болезни\n"
            "- планирования обследований / чек-апов / визитов к врачу\n"
            "\n"
            "ОБЯЗАТЕЛЬНО на первой итерации tool-use вызови `get_open_questions` "
            "ПАРАЛЛЕЛЬНО с другими data-tool'ами (биомаркерами/анализами/etc).\n"
            "\n"
            "Если в ответе questions=[] — продолжай как обычно, у пользователя "
            "пока не ведётся структурированный список открытых вопросов.\n"
            "\n"
            "Если questions есть:\n"
            "1. Прочитай весь список (там обычно 5-15 пунктов).\n"
            "2. Отбери 1-3 пункта релевантных текущему вопросу пользователя.\n"
            "3. Упомяни их в ответе ОДНИМ блоком в конце — формат:\n"
            "   «**Кстати, в твоём профиле висит давний открытый вопрос:** [пункт]. "
            "   Стоит включить в ближайший чек-ап / обсудить с врачом».\n"
            "4. Не вываливай весь список — это создаёт ощущение «бот тревожный».\n"
            "5. Не дублируй пункт если ты уже упомянул его в этом диалоге раньше.\n"
            "\n"
            "Цель: пользователь годами носит «висящие» открытые вопросы (например, "
            "K+/Mg+ ни разу не сдавали при тиазиде → удлинённый QTc), а бот при "
            "каждом следующем диалоге их не всплывает. Это критическая ошибка "
            "которую мы закрываем. Лучше один раз напомнить чем не напомнить.\n"
            "\n"
            "---\n"
            "\n"
            "# 🧠 ПАМЯТЬ ДИАЛОГА (универсальный)\n"
            "\n"
            "У тебя ВСЕГДА есть полная история этого диалога в `messages[]` "
            "(последние ~20 ходов). Если пользователь ссылается на:\n"
            "- «ты говорил», «ты сам сказал», «мы обсуждали», «как ты предложил»\n"
            "- «это лучше», «тот случай», «та опция», «помнишь?»\n"
            "- короткий follow-up без явного предмета («стоит ли?», «согласен?», «и что?»)\n"
            "\n"
            "ОБЯЗАТЕЛЬНО **перечитай последние 3-5 сообщений** перед ответом — "
            "именно там предмет разговора. Местоимение «это / тот / та» почти "
            "всегда отсылает к ТВОЕМУ предыдущему ответу.\n"
            "\n"
            "❌ ЗАПРЕЩЕНО говорить:\n"
            "- «Похоже, я потерял нить»\n"
            "- «Это новая сессия, предыдущий контекст не сохранился»\n"
            "- «У меня нет памяти о предыдущем разговоре»\n"
            "- «Уточни о чём речь» — БЕЗ предварительного перечитывания истории\n"
            "\n"
            "✅ Если после перечитывания истории действительно неясно — переспроси "
            "КОНКРЕТНО: «Про что именно — витамин D, тестостерон, давление?» — "
            "но не делай вид что памяти нет. У тебя она есть.\n"
            "\n"
            "Прецедент 25.05.2026 22:48: пользователь спросил «ты сам говорил "
            "что это лучше, стоит ли повышать?» сразу после твоего же ответа про "
            "витамин D 35.8 нг/мл и опцию 7000-8000 МЕ. История в payload была. "
            "Ты ошибочно ответил «потерял нить» вместо того чтобы понять что "
            "«это» = «целевой уровень 50+ нг/мл» из 627. Не повторяй.\n"
            "\n"
            "---\n"
            "\n"
            "# 📚 НАУЧНЫЕ ССЫЛКИ — НЕ ВЫДУМЫВАЙ РЕКВИЗИТЫ (универсальный)\n"
            "\n"
            "Когда опираешься на научные данные/гайдлайны — НЕ приписывай "
            "конкретные реквизиты (автор, журнал, год, номер исследования), "
            "если не уверен в них на 100%. LLM систематически путают "
            "журнал/год/авторов — это создаёт ложное доверие и ловит на "
            "неточной цитате (врач пользователя заметит).\n"
            "\n"
            "❌ ЗАПРЕЩЕНО (выдуманная точность):\n"
            "- «Choi et al, NEJM, 2004 показали…» (можешь перепутать журнал/год)\n"
            "- «согласно исследованию 2019 года в Lancet…»\n"
            "- конкретные проценты/RR/HR с приписыванием их названному источнику\n"
            "\n"
            "✅ РАЗРЕШЕНО (обобщённо, честно):\n"
            "- «по данным исследований / по современным рекомендациям…»\n"
            "- «крупные гайдлайны (ESC, EASL, ADA) сходятся в том, что…»\n"
            "- называть ОРГАНИЗАЦИЮ-источник (ВОЗ, ESC, AHA, EASL) — это надёжно,\n"
            "  но БЕЗ выдуманного года/номера документа если не уверен.\n"
            "\n"
            "Цель: рекомендации остаются доказательными, но без галлюцинированных "
            "реквизитов. Лучше «по данным исследований» без ссылки, чем красивая "
            "ссылка с неверным журналом. Прецедент 01.06.2026: бот сослался на "
            "«Choi et al, NEJM 2004» в разборе алкоголя — исследование реально "
            "существует, но реквизиты модель могла исказить.\n"
            "\n"
            "---\n"
            "\n"
            "# 🥦 НУТРИЦИОЛОГИЯ И МЕХАНИЗМЫ — НЕ ВЫДУМЫВАЙ, НЕ КАТЕГОРИЧНИЧАЙ (универсальный)\n"
            "\n"
            "Питание и «как что влияет на организм» — зона, где легче всего "
            "звучать авторитетно и при этом ошибиться. Три правила:\n"
            "\n"
            "1️⃣ НЕ приписывай конкретный биохимический механизм там, где есть "
            "только наблюдательная связь. Если продукт «у части людей "
            "провоцирует» что-то — так и скажи, БЕЗ выдуманной биохимии.\n"
            "   ❌ «томаты повышают мочевую кислоту через глутамат и фруктозу» "
            "(механизм выдуман)\n"
            "   ✅ «у части людей с подагрой томаты субъективно провоцируют "
            "обострения, хотя пуринов в них мало — механизм неясен»\n"
            "\n"
            "2️⃣ НЕ подавай диетологические мифы как факт.\n"
            "   ❌ «углеводы на ночь откладываются в жир эффективнее, чем днём» "
            "(миф — решает суточный калораж, не время)\n"
            "   ✅ «вечером легче переесть; при дефиците калорий поздний "
            "углеводный перекус проще убрать — но дело в суточном балансе, "
            "не в самом времени»\n"
            "\n"
            "3️⃣ Смягчай категоричность. Избегай «безопасной дозы нет», "
            "«всегда», «доказано» если это лишь преобладающее мнение. Лучше "
            "«обычно», «по большинству данных», «как правило». Конкретные "
            "цифры (мг пуринов на 100 г, ккал, нормы) давай как «примерно» и "
            "только если уверен — лучше диапазон, чем точное выдуманное число.\n"
            "\n"
            "Цель: советы остаются полезными и по делу, но без псевдо-биохимии "
            "и завышенной уверенности. Пользователь может процитировать тебя "
            "своему врачу — не подставь его выдуманным механизмом.\n"
            "Прецедент 01.06.2026: аудит 9 ответов Диме — про его данные всё "
            "верно, но «глутамат в томатах», «углеводы на ночь толстят», "
            "завышенные пурины горошка (50-80 вместо ~15-25 мг) — неточности.\n"
            "\n"
            "---\n"
            "\n"
        )
        per_user_prompt = user.agent_system_prompt or ""
        # 📅 Инжектим сегодняшнюю дату в таймзоне юзера. Без неё LLM угадывает
        # «сегодня» (и ошибается: e2e 01.06.2026 — агент решил, что сегодня 02.06,
        # и «вчера» посчитал как 01.06). Нужно для корректного log_meal_text с
        # относительной датой и любых «вчера/на той неделе». Дата меняется раз в
        # сутки → префикс кэша обновляется раз в день (незначимо).
        _tz_name = getattr(user, "timezone", None) or "Europe/Moscow"
        try:
            from zoneinfo import ZoneInfo

            _now_local = datetime.now(ZoneInfo(_tz_name))
        except Exception:
            _now_local = datetime.now(timezone.utc)
        _weekday_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][
            _now_local.weekday()
        ]
        _date_line = (
            f"📅 Сегодня: {_now_local.strftime('%Y-%m-%d')} ({_weekday_ru}), "
            f"таймзона пользователя {_tz_name}. Все относительные даты «вчера», "
            "«позавчера», «на той неделе» считай строго от этой даты.\n\n"
        )
        merged_system_prompt = _date_line + UNIVERSAL_META_PROMPT + per_user_prompt
        # Prompt caching: system prompt + tool definitions cached at $0.30/MT
        # instead of $3.00/MT on subsequent calls (Sonnet 4.6). Cache TTL 5 min
        # default, refreshed by every cache hit. Within a single conversation
        # (multi-iteration tool loop) the second+ iteration always hits cache.
        # `cache_control: ephemeral` on the LAST tool entry caches everything
        # before it (system + all tools). See:
        # https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
        cached_tools = [dict(t) for t in TOOLS]
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
        anthropic_beta_header = {"anthropic-beta": "prompt-caching-2024-07-31"}
        # Merge into headers (don't mutate the outer headers dict)
        request_headers = {**headers, **anthropic_beta_header}

        for iteration in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "output_config": {"effort": AGENT_EFFORT},
                "system": [
                    {
                        "type": "text",
                        "text": merged_system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "tools": cached_tools,
                "messages": history,
            }
            logger.info(
                "agent_chat call: user=%s iter=%s msgs=%s",
                user_id,
                iteration,
                len(history),
            )
            # Helper: ретрай на overload-коды Anthropic (529 Overloaded, 503 Service Unavailable,
            # 429 Rate Limited). API сам рекомендует exponential backoff.
            import time as _time

            def _post_with_overload_retry(p):
                # Strategy: fast fallback. Anthropic 529 обычно сигнализирует
                # пиковую нагрузку на конкретный compute pool — короткий retry
                # её не разгребает. Лучше быстро прыгнуть на 4.5 (другой pool).
                # Раньше было 1+2+4=7s ожиданий, юзер видел "думаю..." 10+ сек.
                # Теперь: 1 быстрый retry (0.7s), потом сразу fallback.
                resp = requests.post(ANTHROPIC_API_URL, headers=request_headers, json=p, timeout=60)
                if resp.status_code not in (429, 503, 529):
                    return resp
                logger.warning(
                    "Anthropic %d on %s — quick retry in 0.7s",
                    resp.status_code,
                    p.get("model", MODEL),
                )
                _time.sleep(0.7)
                resp = requests.post(ANTHROPIC_API_URL, headers=request_headers, json=p, timeout=60)
                if resp.status_code not in (429, 503, 529):
                    return resp
                # Всё ещё overload → fallback на 4.5 (другой compute pool)
                if p.get("model") != FALLBACK_MODEL:
                    logger.warning(
                        "Anthropic %d on %s after retry — fallback to %s",
                        resp.status_code,
                        p.get("model", MODEL),
                        FALLBACK_MODEL,
                    )
                    p = {**p, "model": FALLBACK_MODEL}
                    # Sonnet 4.5 не поддерживает output_config.effort → снимаем,
                    # иначе вернёт 400 на fallback-вызове.
                    p.pop("output_config", None)
                    resp = requests.post(ANTHROPIC_API_URL, headers=request_headers, json=p, timeout=60)
                return resp

            r = _post_with_overload_retry(payload)
            # Anthropic returns 400 when message history has structural issues
            # (e.g. tool_use block without matching tool_result from a previous
            # turn). Recover by retrying with a clean slate.
            if r.status_code == 400 and iteration == 0 and len(history) > 1:
                err_body = r.text[:500]
                logger.warning(
                    "agent_chat 400 from Anthropic with %d history msgs — retrying with fresh history. Body: %s",
                    len(history),
                    err_body,
                )
                history = [{"role": "user", "content": user_text}]
                payload["messages"] = history
                r = _post_with_overload_retry(payload)
            r.raise_for_status()
            response = r.json()

            # Best-effort usage logging — never blocks
            try:
                from core.llm_usage import log_anthropic_response

                log_anthropic_response(
                    purpose="agent_chat_tool" if iteration > 0 else "agent_chat",
                    model=MODEL,
                    response_json=response,
                    user_id=user_id,
                )
            except Exception:
                logger.exception("agent_chat: usage logging failed")

            stop_reason = response.get("stop_reason")
            blocks = response.get("content", [])

            if stop_reason == "tool_use":
                # Record assistant turn (text + tool_use blocks)
                _save_message(db, user_id, "assistant", blocks, source=src)
                history.append({"role": "assistant", "content": blocks})

                # Прогресс по tools этого turn'a. Если в одном turn модель
                # просит несколько tools (типично — get_weight + get_trends)
                # — берём label первого render-tool если он есть, иначе
                # первого read/write tool. render имеет приоритет потому что
                # это самая «зрелищная» операция.
                if progress_cb:
                    tool_names = [b["name"] for b in blocks if b.get("type") == "tool_use"]
                    render_tools = [n for n in tool_names if n in ("render_chart", "render_report")]
                    pick = render_tools[0] if render_tools else (tool_names[0] if tool_names else None)
                    if pick:
                        label = _TOOL_PROGRESS_LABEL.get(pick, "📡 запрос данных")
                        try:
                            progress_cb(label)
                        except Exception:
                            logger.exception("progress_cb tool failed")

                # Execute each tool_use, collect tool_result blocks
                tool_results: list[dict] = []
                for block in blocks:
                    if block.get("type") != "tool_use":
                        continue
                    name = block["name"]
                    args = block.get("input", {})
                    tu_id = block["id"]
                    logger.info("agent_chat tool: %s args=%s", name, args)
                    result_text = _call_tool(name, args, token)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": result_text,
                        }
                    )

                _save_message(db, user_id, "tool_result", tool_results, source=src)
                history.append({"role": "user", "content": tool_results})
                db.commit()
                continue  # next iteration — model will incorporate tool results

            # stop_reason in ("end_turn", "max_tokens", "stop_sequence") — final
            _save_message(db, user_id, "assistant", blocks, source=src)
            db.commit()

            # Extract text
            text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
            return "\n".join(text_parts).strip()

        # Exhausted iterations
        logger.warning("agent_chat: max iterations (%s) hit", MAX_TOOL_ITERATIONS)
        return "Не справился за разумное число шагов — попробуй переформулировать вопрос."
    finally:
        db.close()
