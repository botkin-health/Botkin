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
from typing import Any, Optional

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
# Sonnet 4.6 — последняя Sonnet (вышла после Sonnet 4.5 которая использовалась
# в NanoClaw). Та же цена ($3/MT input, $15/MT output), лучше reasoning + tool use.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000
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
        "description": "Недавние приёмы пищи. days=1..30, по умолчанию 3.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 3}},
        },
    },
    {
        "name": "get_kb_value",
        "description": "Значение из knowledge base по ключу. Распространённые ключи: 'blood_tests', 'hormones', 'vitamins', 'blood_pressure_history', 'weight_history', 'allergies'.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
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
        "description": "Сон за последние N дней (1-90, по умолчанию 14). Возвращает каждую ночь + средняя продолжительность, качество, deep/REM/awake минуты.",
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
            "Per-day тренды HRV, Body Battery, Stress, Steps, RHR, Sleep "
            "за N дней (по умолчанию 14). В отличие от get_dashboard_summary "
            "который даёт только AVG за 7 дней — тут видно динамику ДЕНЬ ЗА ДНЁМ. "
            "Используй для 'падает ли мой HRV', 'когда у меня был стресс', "
            "'какой у меня body battery утром', 'как менялся пульс покоя'. "
            "Возвращает items (per-day) + stats (avg/min/max)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
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
            "ВАЖНО: возвращает агрегаты (экстремумы + даты), а не сырой список из "
            "сотен записей. Если нужна динамика по дням — это отдельный tool (пока нет)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 7,
                    "maximum": 365,
                    "description": "Опционально: окно в днях для дополнительных in_window-агрегатов. Без параметра — только all_time.",
                }
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
        "description": "Залогировать приём пищи из текстового описания. ИСПОЛЬЗОВАТЬ ТОЛЬКО если юзер ЯВНО просит 'запиши' или 'залогируй'. Не пытайся логировать каждое упоминание еды.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "slot": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                },
            },
            "required": ["text"],
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
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_meals",
                params={"days": days},
                headers=headers,
                timeout=15,
            )
        elif name == "get_kb_value":
            r = requests.get(
                f"{TOOLS_API_BASE}/kb_value",
                params={"key": args["key"]},
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
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_weight_history":
            params: dict[str, Any] = {}
            if "days" in args and args["days"] is not None:
                params["days"] = int(args["days"])
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
        elif name == "log_bp":
            r = requests.post(f"{TOOLS_API_BASE}/log_bp", json=args, headers=headers, timeout=10)
        elif name == "log_supplement":
            r = requests.post(f"{TOOLS_API_BASE}/log_supplement", json=args, headers=headers, timeout=10)
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

    sql = text(
        """
        SELECT role, content
        FROM agent_conversations
        WHERE user_id = :uid
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


def _save_message(db, user_id: int, role: str, content: Any, tool_use_id: Optional[str] = None):
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO agent_conversations (user_id, role, content, tool_use_id)
            VALUES (:uid, :role, CAST(:content AS JSONB), :tid)
            """
        ),
        {
            "uid": user_id,
            "role": role,
            "content": json.dumps(content),
            "tid": tool_use_id,
        },
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def ask_agent(user_id: int, user_text: str) -> str:
    """Synchronous — call from `run_in_executor`.

    Returns assistant's text reply. Empty string if nothing produced.
    Errors are raised; caller (handler) catches and replies "технически не вышло".
    """
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

        # Build messages: history + new user turn
        history = _load_history(db, user_id)
        history.append({"role": "user", "content": user_text})

        # Persist user turn immediately so a crash mid-call doesn't lose it.
        _save_message(db, user_id, "user", user_text)
        db.commit()

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

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
                "system": [
                    {
                        "type": "text",
                        "text": user.agent_system_prompt,
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
            r = requests.post(ANTHROPIC_API_URL, headers=request_headers, json=payload, timeout=60)
            # Anthropic returns 400 when message history has structural issues
            # (e.g. tool_use block without matching tool_result from a previous
            # turn). This can happen if a row was deleted, the DB had a partial
            # write, or older history was corrupted by an earlier bug. Recover
            # by retrying with a clean slate (just system + new user turn),
            # marking the broken history so the user understands context was
            # dropped.
            if r.status_code == 400 and iteration == 0 and len(history) > 1:
                err_body = r.text[:500]
                logger.warning(
                    "agent_chat 400 from Anthropic with %d history msgs — retrying with fresh history. Body: %s",
                    len(history),
                    err_body,
                )
                # Reset to just the new user message
                history = [{"role": "user", "content": user_text}]
                payload["messages"] = history
                r = requests.post(ANTHROPIC_API_URL, headers=request_headers, json=payload, timeout=60)
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
                _save_message(db, user_id, "assistant", blocks)
                history.append({"role": "assistant", "content": blocks})

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

                _save_message(db, user_id, "tool_result", tool_results)
                history.append({"role": "user", "content": tool_results})
                db.commit()
                continue  # next iteration — model will incorporate tool results

            # stop_reason in ("end_turn", "max_tokens", "stop_sequence") — final
            _save_message(db, user_id, "assistant", blocks)
            db.commit()

            # Extract text
            text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
            return "\n".join(text_parts).strip()

        # Exhausted iterations
        logger.warning("agent_chat: max iterations (%s) hit", MAX_TOOL_ITERATIONS)
        return "Не справился за разумное число шагов — попробуй переформулировать вопрос."
    finally:
        db.close()
