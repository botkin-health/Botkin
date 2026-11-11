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
import os
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typing import Any, Callable, Optional

import jwt as pyjwt
import requests

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings
from database import SessionLocal
from database.rls import bind_user, user_context
from database.models import User, log_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Выбор моделей и история откатов — config/models.py (env-переопределяемо).
# Основная модель и fallback (Sonnet 5 / Sonnet 4.6) обе поддерживают
# output_config.effort — ⚠️ если fallback когда-нибудь укажет на Sonnet 4.5,
# effort надо будет снимать в _post_with_overload_retry, иначе 400.
from config.models import AGENT_FALLBACK_MODEL as FALLBACK_MODEL
from config.models import AGENT_MODEL as MODEL

# effort=medium — документированный sweet spot для чата: дешевле и
# быстрее дефолтного high, без потери качества на разговорных задачах.
AGENT_EFFORT = "medium"
MAX_TOKENS = 4000  # 2000 обрезал развёрнутые многофакторные ответы (прецедент:
# разбор «алкоголь по всем диагнозам» Димы оборвался на полуслове). 4000 хватает
# на полный разбор с таблицей; короткие ответы лимит не трогает (бот сам краток).
MAX_TOOL_ITERATIONS = 6  # safety net against tool loops
HISTORY_WINDOW = 20  # last N messages from agent_conversations
STALE_HISTORY_GUARD = os.getenv("AGENT_STALE_HISTORY_GUARD") == "1"  # P-003, см. цикл инструментов
TRACKER_HISTORY_ROWS = 12  # до 6 пар быстрых записей поверх окна диалога

# Универсальные правила агента поверх per-user промпта. Сжаты 28.09.2026:
# 14.5K → 6.1K токенов на каждом вызове, правила и якоря тестов сохранены.
UNIVERSAL_META_PROMPT = (Path(__file__).resolve().parent / "llm" / "prompts" / "agent_meta_system.txt").read_text(
    encoding="utf-8"
)

# Tools API base URL — same container, FastAPI on 8081.
# When running inside healthvault_bot container, this is localhost:8081 directly.
TOOLS_API_BASE = "http://localhost:8081/api/agent"

# Единый TTL с webhook/jwt_auth.py (тот же env) — раньше тут было 24h против 1h
# у валидатора, политика противоречила сама себе. Токен регенерируется на каждый
# запрос пользователя, 1 часа хватает на самый длинный tool-loop с запасом.
JWT_TTL_HOURS = int(os.getenv("AGENT_JWT_TTL_HOURS", "1"))

# ---------------------------------------------------------------------------
# Tool schema (BotkinClaw tools — wrap webhook/agent_tools_api.py endpoints)
# ---------------------------------------------------------------------------

# Описания — только то, что помогает выбрать тул и заполнить аргументы.
# Общие правила (свежий вызов на любой вопрос о данных, план→факт, глюкоза,
# протокол медвопроса, добавки vs медпрофиль, дата при записи прошлого)
# живут в agent_meta_system.txt и в _date_line — здесь их не повторяем:
# схемы тулов идут в каждый промпт и пишутся в кэш на каждом ходе после паузы.
_DAYS = {"type": "integer", "minimum": 1}
_DATE_ARG = {"type": "string", "description": "YYYY-MM-DD"}
_NO_ARGS = {"type": "object", "properties": {}}
_SLOT = {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]}
_WHEN_ARG = {
    "type": "string",
    "description": "ISO datetime или YYYY-MM-DD, только если пользователь назвал день/время; иначе не передавай (=сейчас).",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_user_profile",
        "description": "Базовый профиль: имя, возраст, рост, пол, когорта. Обычно не нужен — он уже в system prompt.",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_dashboard_summary",
        "description": (
            "Сводка за 7 дней: средние шаги, пульс, активные и съеденные ккал, последний вес и % жира, "
            "плюс `dashboard_url` — ссылка на веб-дашборд. Для «как мои дела / неделя / прогресс» и просьб "
            "показать дашборд."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "meal_context",
        "description": (
            "Всё для «что мне съесть / что на ужин» одним вызовом: остаток КБЖУ на сегодня, constraints "
            "(диагнозы-ограничения), allergies, любимые продукты. Варианты — без продуктов из allergies. "
            "constraints_source=none — данных нет, ограничения не выдумывай."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_recent_meals",
        "description": (
            "Приёмы пищи за days дней (у записи есть id и status eaten|plan). Поиск по длинному периоду "
            "(«ел ли я X за месяц») — большой days и compact=true; при days>14 compact включается сам. "
            "Тренд за полгода/год — days до 366 и daily=true (по дням ккал/БЖУ; при days>90 сам)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {**_DAYS, "maximum": 366, "default": 3},
                "compact": {"type": "boolean", "default": False, "description": "Только имена продуктов и ккал."},
                "daily": {"type": "boolean", "default": False, "description": "Подневные суммы КБЖУ вместо приёмов."},
                "only_open_plans": {
                    "type": "boolean",
                    "default": False,
                    "description": "Только открытые планы за сегодня (status=plan).",
                },
            },
        },
    },
    {
        "name": "get_recent_glucose",
        "description": (
            "Глюкоза CGM: точки (ts, mmol/L, trend) и stats (avg/min/max/TIR) за последние hours часов или за "
            "календарный день date. Точки прорежены по окну, stats — по всем точкам. В пустом ответе "
            "`last_point_ever_local`/`days_since_last_point` — последняя точка за всю историю. "
            "is_stale / refresh_skipped — данные несвежие."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {**_DAYS, "maximum": 168, "default": 24},
                "date": {"type": "string", "description": "YYYY-MM-DD в TZ пользователя; приоритетнее hours"},
            },
        },
    },
    {
        "name": "get_glucose_stats",
        "description": "Статистика глюкозы CGM за days дней: TIR% (3.9–10), среднее, std, min/max, % ниже/выше.",
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 90, "default": 7}}},
    },
    {
        "name": "get_daily_metrics",
        "description": (
            "Посуточные метрики Apple Health: сатурация, VO2max, частота дыхания, температура запястья, "
            "min/max пульса, фазы сна (deep/rem/core/awake), походка, этажи. `available` — по скольким дням "
            "метрика есть; не говори «такое не собирается», не заглянув сюда."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 180, "default": 14}}},
    },
    {
        "name": "get_recent_ecg",
        "description": (
            "ЭКГ с Apple Watch: дата, заключение (sinusRhythm, atrialFibrillation…), пульс, симптомы. "
            "Отдельный источник от клинических ЭКГ в KB."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 365, "default": 90}}},
    },
    {
        "name": "get_heart_rate_events",
        "description": (
            "Уведомления Apple Watch о пульсе вне нормы в покое (высокий/низкий/нерегулярный): время, порог, "
            "пульс, длительность. Для «была ли тахикардия» и сопоставления эпизодов с глюкозой по времени."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 365, "default": 90}}},
    },
    {
        "name": "list_kb_keys",
        "description": (
            "Ключи knowledge_base этого пользователя с type и count (схемы у людей разные: echocardiogram, "
            "mrt, cardio, current_medications…). Зови первым, если не уверен, под каким ключом лежит "
            "обследование (ЭхоКГ, холтер, МРТ, операции, препараты, диагнозы). `documents` — файлы из /doc."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_kb_value",
        "description": (
            "Значение из knowledge base по ключу, dot-notation ('ultrasound.0', 'agent_corrections.X'). "
            "'documents.N.extracted' — дата, лаборатория и текст загруженного документа, 'documents.N.file' — "
            "имя файла. Лабораторные показатели здесь не ищи — они в get_recent_biomarkers."
        ),
        "input_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    },
    {
        "name": "list_documents",
        "description": (
            "Все сохранённые документы профиля — анализы из /doc и прочее (полис, справка, визитка врача): "
            "id, title, category, added_at, is_lab. Для «что у меня сохранено» и чтобы найти id для send_document."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "update_document",
        "description": (
            "Дать название/категорию сохранённому документу. Пользователь прислал файл «про запас» — он уже "
            "в архиве, не отказывай: узнай, что это (если не очевидно), и запиши. document_id — из list_documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "title": {"type": "string", "description": "Напр. «Полис ОМС»"},
                "category": {"type": "string", "enum": ["insurance", "certificate", "contact", "medical", "other"]},
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "send_document",
        "description": "Прислать пользователю в Telegram сохранённый документ («пришли мой полис»). id — из list_documents.",
        "input_schema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
    {
        "name": "get_open_questions",
        "description": (
            "Открытые клинические вопросы и red flags из KB (несданные маркеры, незакрытые follow-up). "
            "questions=[] и source='not-tracked' — списка нет, это нормально."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_recent_bp",
        "description": "Давление за days дней: каждый замер + средние, max/min, % замеров выше 140/90.",
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 90, "default": 14}}},
    },
    {
        "name": "get_intraday_timeline",
        "description": (
            "Хронология дня по получасам: пульс, стресс Garmin, Body Battery, «движение» / «нет данных», "
            "эпизоды высокого стресса с началом и концом. Обязательно при вопросах о самочувствии в конкретный "
            "день и скринах отклонений с часов — суточные средние на них не отвечают. available=false — "
            "почасовых данных нет."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; по умолчанию сегодня"}},
        },
    },
    {
        "name": "get_recent_sleep",
        "description": (
            "Сон по ночам + средние (длительность, качество, deep/REM), `latest_available_date` — последняя ночь "
            "с данными. Нет прошлой ночи — назови эту дату и скажи, что данные с часов приходят с задержкой "
            "и подтягиваются каждые ~30 минут (или /sync); конкретное время не выдумывай."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 90, "default": 14}}},
    },
    {
        "name": "get_recent_supplements",
        "description": (
            "Лог приёма добавок по каждой: days_taken, total_intakes, adherence_pct, last_date, last_dosage. "
            "Источник для «что я принимаю / как часто пил магний»; список из system prompt может устареть."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 180, "default": 30}}},
    },
    {
        "name": "get_supplement_daily_log",
        "description": (
            "Даты приёма каждой добавки (taken_dates) за окно — для корреляций по дням («влияет ли магний "
            "на сон»): дня нет в списке = не принимал. Дозы по датам — в intakes (если доза менялась); "
            "last_dosage на прошлые даты не растягивай."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {**_DAYS, "maximum": 180, "default": 30},
                "supplement": {"type": "string", "description": "Фильтр по подстроке имени"},
            },
        },
    },
    {
        "name": "get_recent_biomarkers",
        "description": (
            "История анализов крови, гормонов, витаминов (blood_tests): дата, тип, values по маркерам. "
            "Для динамики («как менялся ЛПНП», «какие анализы за год»). limit 20 ≈ год, 50 — всё."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        },
    },
    {
        "name": "get_latest_biomarkers",
        "description": (
            "Последнее значение каждого биомаркера с days_ago, is_stale, stale_label — для текущего "
            "значения («какой у меня витамин D»)."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_phenoage",
        "description": (
            "Биологический возраст PhenoAge (Levine 2018): bio_age, delta_years и 9 маркеров с younger/older. "
            "Не хватает маркеров — вернёт error со списком."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_recent_workouts",
        "description": (
            "Тренировки: by_type (счётчик по типу), Z2 и HIIT мин/нед, A:C load ratio, распределение по зонам, "
            "extremes_by_type, последние 15 тренировок. Тип определяй по `type`, не по `name` (это название "
            "маршрута). «Самая длинная/дальняя» — из extremes_by_type, не из items. «За год» — days=180. "
            "`source` — полные данные (file) или только базовые поля (db)."
        ),
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 180, "default": 30}}},
    },
    {
        "name": "get_menstrual_data",
        "description": (
            "Менструальный цикл из Apple Health: дни с flow, начала циклов, длины циклов, "
            "avg_cycle_days, variation_days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"months": {"type": "integer", "minimum": 1, "maximum": 24, "default": 6}},
        },
    },
    {
        "name": "get_recent_trends",
        "description": (
            "По дням: HRV, Body Battery, стресс, шаги, пульс покоя, сон и флаг alcohol (из лога еды) + stats. "
            "Для динамики и корреляций («алкоголь → HRV следующего дня»). Корреляции и графики — "
            "full_series=true и days=90..180."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {**_DAYS, "maximum": 180, "default": 14},
                "full_series": {
                    "type": "boolean",
                    "default": False,
                    "description": "Все точки окна, а не последние 30.",
                },
            },
        },
    },
    {
        "name": "get_weight_history",
        "description": (
            "Вес и состав тела: latest, all_time (рекорды с датами), in_window (при days). У замеров Withings "
            "есть heart_rate (пульс покоя натощак), bmr_kcal (измеренный — бери его, а не формулу), "
            "fat_mass_kg / lean_mass_kg. Если в latest они пустые — бери из `body_composition` и назови его дату. "
            "series=true добавляет `points` (дата, вес, жир, pulse) — для графиков и тренда пульса."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 7,
                    "maximum": 365,
                    "description": "Окно; без него — только all_time.",
                },
                "series": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "get_body_measurements",
        "description": "Обхваты (талия, шея, бёдра, грудь, бедро, бицепс, см): latest, min/max, тренд талии.",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_user_settings",
        "description": (
            "Цели и настройки: target_weight_kg и дата, supplements_regimen (запланированные добавки со слотами), "
            "calorie_goal_pct, BMR-источник, напоминания, профиль."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "get_profile_questionnaire",
        "description": (
            "Анкета: пол, рост, дата рождения, timezone, smoking_status, kb_status (приватность KB), "
            "garmin_connected, превью agent_system_prompt. Вызывай перед update_profile_questionnaire."
        ),
        "input_schema": _NO_ARGS,
    },
    {
        "name": "update_profile_questionnaire",
        "description": (
            "Изменить поля анкеты (только переданные). Сначала подтверди с пользователем, что меняешь — "
            "особенно agent_system_prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sex": {"type": "string", "enum": ["male", "female", "other"]},
                "height_cm": {"type": "integer", "minimum": 100, "maximum": 250},
                "birth_date": _DATE_ARG,
                "timezone": {"type": "string"},
                "smoking_status": {"type": "string", "enum": ["never", "former", "current", "occasional"]},
                "kb_status": {"type": "string", "enum": ["shared", "private"]},
                "pack_name": {"type": "string"},
                "agent_system_prompt": {"type": "string", "description": "Полная замена промпта агента."},
            },
        },
    },
    {
        "name": "save_health_profile",
        "description": (
            "Медпрофиль со слов пользователя: ПОСТОЯННОЕ состояние, постоянная терапия, аллергии («у меня "
            "гипертония», «постоянно пью розувастатин») — или его ответ на твой вопрос об этом. Пиши короткими "
            "пунктами его словами, без своих диагнозов и без данных из документов/KB. Нечего сообщить или не хочет "
            "отвечать — nothing_to_report=true (больше не спрашивать). Разовый приём или пропуск дозы — СОБЫТИЕ "
            "для log_supplement, не замена ему."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chronic_conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Хронические состояния и постоянные лекарства, как назвал пользователь",
                },
                "allergies": {"type": "array", "items": {"type": "string"}},
                "nothing_to_report": {"type": "boolean"},
            },
        },
    },
    {
        "name": "update_user_settings",
        "description": (
            "Изменить настройки (только переданные поля). supplements — ПОЛНАЯ замена списка: чтобы добавить "
            "одну, сначала get_user_settings, затем весь новый список. Перед изменением подтверди с пользователем."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_weight_kg": {"type": "number", "minimum": 30, "maximum": 300},
                "target_weight_date": _DATE_ARG,
                "calorie_goal_pct": {
                    "type": "integer",
                    "minimum": -50,
                    "maximum": 50,
                    "description": "-15 = дефицит 15%",
                },
                "bmr_override": {"type": "integer", "minimum": 500, "maximum": 5000},
                "bmr_source": {"type": "string", "enum": ["auto", "override", "fixed"]},
                "supplement_reminders_enabled": {"type": "boolean"},
                "supplement_reminder_time": {"type": "string", "description": "HH:MM"},
                "show_calorie_budget_bar": {"type": "boolean"},
                "supplements": {
                    "type": "array",
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
        "description": "Воздух дома (Netatmo, только owner-cohort): CO2, температура, влажность, шум. CO2 >1400 ppm — плохо для сна.",
        "input_schema": {"type": "object", "properties": {"days": {**_DAYS, "maximum": 60, "default": 7}}},
    },
    {
        "name": "get_outdoor_weather",
        "description": "Погода в Москве (Open-Meteo): температура, давление, влажность, UV, осадки. Без date — последний день.",
        "input_schema": {"type": "object", "properties": {"date": _DATE_ARG}},
    },
    {
        "name": "get_day_summary",
        "description": "Сводка за конкретный день: ккал/БЖУ, тренировка, сон, вес, АД. Нет данных — no_data.",
        "input_schema": {"type": "object", "properties": {"date": _DATE_ARG}, "required": ["date"]},
    },
    {
        "name": "log_meal_text",
        "description": (
            "Записать еду из текста — по просьбе («запиши», «да, внеси») или когда сообщение и есть отчёт о еде "
            "(«на обед гречка с котлетой»). Еду, упомянутую в разговоре о другом, не пиши — предложи записать. "
            "Показывает карточку «Сохранить/Отмена». Прошлый день — в date, и назови дату в ответе. "
            "Дописка («забыл добавить») — сначала get_recent_meals(days=2) и тот же slot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD, только если назван день; иначе сегодня."},
                "slot": _SLOT,
                "as_plan": {
                    "type": "boolean",
                    "default": False,
                    "description": "Еда внесена авансом («план:», «на день:», «планирую»)",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "edit_meal",
        "description": (
            "Изменить записанный приём: перенести на день (new_date), сменить слот (new_slot), переименовать. "
            "Передавай только меняемые поля."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {"type": "integer", "description": "id из get_recent_meals"},
                "new_date": _DATE_ARG,
                "new_slot": _SLOT,
                "new_name": {"type": "string"},
            },
            "required": ["meal_id"],
        },
    },
    {
        "name": "delete_meal",
        "description": "Удалить запись о еде по просьбе. Перенос на другой день — edit_meal, не delete+log.",
        "input_schema": {
            "type": "object",
            "properties": {"meal_id": {"type": "integer", "description": "id из get_recent_meals"}},
            "required": ["meal_id"],
        },
    },
    {
        "name": "adjust_meal_items",
        "description": (
            "Свести план к факту внутри записи meal_id: new_weight (г) или remove для item по индексу idx. "
            "Остаток — новой записью-планом в leftover_to_slot (+leftover_to_date). close_plan=true закрывает "
            "план; changes=[] + close_plan — «съела всё». Сначала dry_run=true и подтверждение, потом dry_run=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {"type": "integer"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "idx": {"type": "integer"},
                            "new_weight": {"type": "number"},
                            "remove": {"type": "boolean"},
                        },
                        "required": ["idx"],
                    },
                },
                "leftover_to_slot": _SLOT,
                "leftover_to_date": _DATE_ARG,
                "close_plan": {"type": "boolean", "default": False},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["meal_id", "changes"],
        },
    },
    {
        "name": "log_bp",
        "description": "Записать давление. Прошлый день — назови дату в ответе.",
        "input_schema": {
            "type": "object",
            "properties": {
                "systolic": {"type": "integer"},
                "diastolic": {"type": "integer"},
                "pulse": {"type": "integer"},
                "measured_at": {
                    **_WHEN_ARG,
                    "description": _WHEN_ARG["description"]
                    + " «Утром/вечером» — с временем (~08:00 / ~20:00), не одной датой.",
                },
            },
            "required": ["systolic", "diastolic"],
        },
    },
    {
        "name": "log_weight",
        "description": (
            "Записать вес тела, названный пользователем («82,5», «вешу 80», ответ на твой вопрос). "
            "Не для чужого, целевого веса и веса продуктов."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"weight": {"type": "number", "description": "кг"}, "measured_at": _WHEN_ARG},
            "required": ["weight"],
        },
    },
    {
        "name": "log_workout",
        "description": (
            "Записать тренировку вручную (нет интеграции с часами или рассказал словами) — только по явной "
            "просьбе. Повтор с тем же start_time обновляет запись (уточнение «нет, 45 минут»). "
            "status=conflict_other_source — тренировка уже есть с часов, ничего не записано: скажи об этом "
            "или уточни время."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_type": {"type": "string", "description": "Напр. 'бег', 'силовая'"},
                "duration_minutes": {"type": "integer"},
                "distance_km": {"type": "number"},
                "calories_burned": {"type": "integer"},
                "avg_heart_rate": {"type": "integer"},
                "max_heart_rate": {"type": "integer"},
                "start_time": {**_WHEN_ARG, "description": "YYYY-MM-DDTHH:MM:SS, только если назван день/время."},
            },
            "required": ["workout_type"],
        },
    },
    {
        "name": "log_supplement",
        "description": (
            "Записать фактический приём добавки/лекарства (не описание схемы). Приём или пропуск дозы в прошлом "
            "(«выпил капотен позавчера») — тоже событие: запиши его с `date`/`time`, даже если заодно "
            "сохраняешь терапию в save_health_profile. status=duplicate_warning — уже было сегодня, ничего не "
            "записано: уточни и при подтверждении повтори с force=true. Исправить запись — edit_supplement_log."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplement_name": {"type": "string"},
                "dosage": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD, только если назван день; иначе сегодня."},
                "time": {"type": "string", "description": "HH:MM, только если назвал."},
                "force": {"type": "boolean", "description": "Подтверждённый повторный приём."},
            },
            "required": ["supplement_name"],
        },
    },
    {
        "name": "edit_supplement_log",
        "description": (
            "Исправить или удалить записанный приём добавки. Передай date и supplement (и dosage_from, если "
            "записей несколько) плюс одно действие: new_dosage, new_date, new_supplement_name или delete=true "
            "(только по явной просьбе). ambiguous / not_found — покажи candidates, после выбора повтори с log_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": _DATE_ARG,
                "supplement": {"type": "string"},
                "dosage_from": {"type": "string"},
                "log_id": {"type": "integer"},
                "new_dosage": {"type": "string"},
                "new_date": _DATE_ARG,
                "new_supplement_name": {"type": "string"},
                "delete": {"type": "boolean"},
            },
        },
    },
    {
        "name": "render_chart",
        "description": (
            "Нарисовать график (QuickChart → Telegram) для всего, что не покрывает render_report. "
            "chart — Chart.js v4, минимально: type, data.labels, data.datasets[].label/data, "
            "options.plugins.title.text (обязательно); options.scales — только для нестандартных осей. "
            "Цвета и стиль ставит сервер — не заполняй. Пример: {type:'line', data:{labels:['янв','фев'], "
            "datasets:[{label:'Вес', data:[82,81]}]}, options:{plugins:{title:{text:'Вес'}}}}. "
            "Потом — 1–3 предложения, картинку не пересказывай."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart": {"type": "object"},
                "caption": {"type": "string", "description": "Подпись к фото, 1 строка без markdown"},
                "width": {"type": "integer", "default": 600, "minimum": 200, "maximum": 1600},
                "height": {"type": "integer", "default": 400, "minimum": 200, "maximum": 1200},
            },
            "required": ["chart"],
        },
    },
    {
        "name": "render_report",
        "description": (
            "Отправить в Telegram PNG-инфографику по анализам — вместо markdown-таблицы с динамикой. "
            "biomarker_dynamics — панель 6 ключевых маркеров (общая картина, для врача); single_biomarker + "
            "marker — график одного маркера (рус. или лат.: «витамин Д», LDL, HbA1c). Потом — 2–4 предложения."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["biomarker_dynamics", "single_biomarker"],
                    "default": "biomarker_dynamics",
                },
                "marker": {"type": "string"},
            },
        },
    },
    {
        "name": "generate_doctor_report",
        "description": (
            "Отправить в Telegram PDF-отчёт для врача (проблемы, аллергии, лекарства, анализы, витальные). "
            "Не график — для него render_report. Потом коротко: отчёт отправлен, можно переслать врачу."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["ru", "en"], "description": "'en' — если просят на английском"}
            },
        },
    },
    {
        "name": "add_agent_correction",
        "description": (
            "Сохранить в KB поправку или новый медицинский факт (дата операции, диагноз, препарат) сразу, "
            "как пользователь его сообщил. Будет доступен в следующих разговорах."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "snake_case, напр. surgery_year"},
                "value": {"type": "string"},
                "reason": {"type": "string", "description": "Слова пользователя"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "flag_for_devs",
        "description": "Передать разработчикам баг или пожелание пользователя.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["bug", "feature", "question"]},
                "user_msg": {"type": "string", "description": "Суть словами пользователя"},
                "agent_note": {"type": "string"},
            },
            "required": ["category", "user_msg"],
        },
    },
    {
        "name": "list_feedback",
        "description": "Админ: записи инбокса обратной связи. По умолчанию status='new'; 'all' — все.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "new/triaged/in_progress/done/wontfix/duplicate/all"},
                "limit": {"type": "integer", "description": "до 100, по умолчанию 20"},
            },
        },
    },
    {
        "name": "triage_feedback",
        "description": (
            "Админ: сменить статус/приоритет записи инбокса, привязать GitHub-issue (только меняемые поля). "
            "На done/wontfix бот сам уведомит автора; для вопроса передай notify_text — ответ уйдёт автору."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feedback_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["new", "triaged", "in_progress", "done", "wontfix", "duplicate"]},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                "github_issue": {"type": "string"},
                "notify_text": {"type": "string"},
            },
            "required": ["feedback_id"],
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


def _user_content_with_images(user_text: str, images: Optional[list]):
    """Текст хода + до трёх картинок (image-блоки Messages API)."""
    if not images:
        return user_text
    import base64

    blocks: list[dict] = []
    for p in list(images)[:3]:
        try:
            raw = Path(p).read_bytes()
        except OSError:
            logger.warning("agent image unreadable: %s", p)
            continue
        media = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        blocks.append(
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(raw).decode()}}
        )
    if not blocks:
        return user_text
    return blocks + [{"type": "text", "text": user_text}]


_SLOT_NAMES = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекус"}


def _preview_meal_text(user_id: int, args: dict, sink: list) -> str:
    """`log_meal_text` в чате бота: распарсить еду и отдать черновик карточки.

    Запись появляется только после «Сохранить» — как у еды, присланной напрямую.
    """
    from core.food.nutrition import process_llm_food_data
    from core.llm.router import analyze_message

    text = (args.get("text") or "").strip()
    try:
        llm_result = analyze_message(text=text, user_id=user_id)
    except Exception as e:
        logger.exception("meal preview: parser failed")
        return json.dumps({"status": "rejected", "reason": f"парсер упал: {e}"}, ensure_ascii=False)
    if not llm_result or llm_result.get("type") not in ("food", "multi_food"):
        return json.dumps(
            {"status": "rejected", "reason": "это не распозналось как еда — уточни продукт и количество"},
            ensure_ascii=False,
        )
    if llm_result.get("type") == "multi_food":
        meals = (llm_result.get("data") or {}).get("meals") or []
        if not meals:
            return json.dumps({"status": "rejected", "reason": "пустой список"}, ensure_ascii=False)
        llm_result = {"type": "food", "data": meals[0]}
    items, totals = process_llm_food_data(llm_result, text, True)
    if not items or not (totals.get("calories") or 0):
        return json.dumps(
            {"status": "rejected", "reason": "не удалось посчитать КБЖУ — нужен продукт и примерный вес"},
            ensure_ascii=False,
        )
    data = llm_result.get("data") or {}
    meal_name = (
        _SLOT_NAMES.get(args.get("slot") or "") or data.get("dish_name") or data.get("meal_type") or "Приём пищи"
    )
    sink.append(
        {
            "text": text,
            "date": args.get("date"),
            "slot": args.get("slot"),
            "as_plan": bool(args.get("as_plan")),
            "meal_name": meal_name,
            "items": items,
            "totals": totals,
        }
    )
    return json.dumps(
        {
            "status": "preview_shown",
            "meal_name": meal_name,
            "date": args.get("date") or "сегодня",
            "calories": round(totals.get("calories") or 0),
            "note": (
                "Пользователь видит карточку с КБЖУ и кнопками «Сохранить/Отмена»; запись появится "
                "после нажатия. Не пиши «записал» — коротко скажи, что карточка ниже."
            ),
        },
        ensure_ascii=False,
    )


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
        elif name == "meal_context":
            r = requests.get(f"{TOOLS_API_BASE}/meal_context", headers=headers, timeout=15)
        elif name == "get_recent_meals":
            days = int(args.get("days", 3))
            params = {"days": days}
            if args.get("compact"):
                params["compact"] = "true"
            if args.get("only_open_plans"):
                params["only_open_plans"] = "true"
            if args.get("daily"):
                params["daily"] = "true"
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
        elif name == "get_intraday_timeline":
            r = requests.get(
                f"{TOOLS_API_BASE}/intraday",
                params={"date": args["date"]} if args.get("date") else {},
                headers=headers,
                timeout=45,
            )
        elif name == "get_recent_sleep":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_sleep",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_glucose":
            glucose_params: dict = {}
            if args.get("date"):
                glucose_params["date"] = str(args["date"])
            else:
                glucose_params["hours"] = int(args.get("hours", 24))
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_glucose",
                params=glucose_params,
                headers=headers,
                timeout=15,
            )
        elif name == "get_glucose_stats":
            r = requests.get(
                f"{TOOLS_API_BASE}/glucose_stats",
                params={"days": int(args.get("days", 7))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_daily_metrics":
            r = requests.get(
                f"{TOOLS_API_BASE}/daily_metrics",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_ecg":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_ecg",
                params={"days": int(args.get("days", 90))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_heart_rate_events":
            r = requests.get(
                f"{TOOLS_API_BASE}/heart_rate_events",
                params={"days": int(args.get("days", 90))},
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
        elif name == "get_supplement_daily_log":
            params = {"days": int(args.get("days", 30))}
            if args.get("supplement"):
                params["supplement"] = str(args["supplement"])
            r = requests.get(
                f"{TOOLS_API_BASE}/supplement_daily_log",
                params=params,
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
        elif name == "get_latest_biomarkers":
            r = requests.get(f"{TOOLS_API_BASE}/latest_biomarkers", headers=headers, timeout=15)
        elif name == "get_phenoage":
            r = requests.get(f"{TOOLS_API_BASE}/phenoage", headers=headers, timeout=15)
        elif name == "get_recent_workouts":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_workouts",
                params={"days": int(args.get("days", 30))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_menstrual_data":
            r = requests.get(
                f"{TOOLS_API_BASE}/menstrual_data",
                params={"months": int(args.get("months", 6))},
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
        elif name == "save_health_profile":
            r = requests.post(
                f"{TOOLS_API_BASE}/save_health_profile",
                json=args,
                headers=headers,
                timeout=15,
            )
        elif name == "list_documents":
            r = requests.get(f"{TOOLS_API_BASE}/list_documents", headers=headers, timeout=10)
        elif name == "update_document":
            doc_args = dict(args)
            document_id = doc_args.pop("document_id", "")
            r = requests.post(
                f"{TOOLS_API_BASE}/update_document",
                params={"document_id": document_id},
                json=doc_args,
                headers=headers,
                timeout=15,
            )
        elif name == "send_document":
            r = requests.post(
                f"{TOOLS_API_BASE}/send_document",
                json=args,
                headers=headers,
                timeout=20,
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
        elif name == "adjust_meal_items":
            r = requests.post(f"{TOOLS_API_BASE}/adjust_meal_items", json=args, headers=headers, timeout=15)
        elif name == "log_bp":
            r = requests.post(f"{TOOLS_API_BASE}/log_bp", json=args, headers=headers, timeout=10)
        elif name == "log_weight":
            r = requests.post(f"{TOOLS_API_BASE}/log_weight", json=args, headers=headers, timeout=10)
        elif name == "log_supplement":
            r = requests.post(f"{TOOLS_API_BASE}/log_supplement", json=args, headers=headers, timeout=10)
        elif name == "edit_supplement_log":
            r = requests.post(f"{TOOLS_API_BASE}/edit_supplement_log", json=args, headers=headers, timeout=10)
        elif name == "log_workout":
            r = requests.post(f"{TOOLS_API_BASE}/log_workout", json=args, headers=headers, timeout=10)
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
        elif name == "generate_doctor_report":
            # Side-effect tool — генерит PDF-отчёт для врача и шлёт sendDocument
            # (общий helper с кнопкой мини-аппа, #290/#291). language — #300.
            r = requests.post(
                f"{TOOLS_API_BASE}/doctor_report",
                headers=headers,
                json={"language": args.get("language")},
                timeout=60,
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
        elif name == "add_agent_correction":
            r = requests.post(
                f"{TOOLS_API_BASE}/add_agent_correction",
                json={
                    "key": args.get("key", ""),
                    "value": args.get("value", ""),
                    "reason": args.get("reason", ""),
                },
                headers=headers,
                timeout=10,
            )
        elif name == "flag_for_devs":
            r = requests.post(
                f"{TOOLS_API_BASE}/flag_for_devs",
                headers=headers,
                json={
                    "category": args.get("category", "question"),
                    "user_msg": args.get("user_msg", ""),
                    "agent_note": args.get("agent_note"),
                },
                timeout=10,
            )
        elif name == "list_feedback":
            r = requests.post(
                f"{TOOLS_API_BASE}/list_feedback",
                headers=headers,
                json={"status": args.get("status", "new"), "limit": args.get("limit", 20)},
                timeout=10,
            )
        elif name == "triage_feedback":
            r = requests.post(
                f"{TOOLS_API_BASE}/triage_feedback",
                headers=headers,
                json={
                    "feedback_id": args.get("feedback_id"),
                    "status": args.get("status"),
                    "priority": args.get("priority"),
                    "github_issue": args.get("github_issue"),
                    "notify_text": args.get("notify_text"),
                },
                timeout=10,
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


def record_failed_turn(user_id: int, error: BaseException, source: str = "botkinclaw") -> None:
    """Зафиксировать несостоявшийся ход агента строкой role='error'.

    Зачем: реплику пользователя `ask_agent` коммитит до обращения к модели, а
    ответ пишется только при успехе. Поэтому сбой выглядит в данных как его
    отсутствие — «не смог ответить» неотличимо от «никто не спрашивал».
    Прецедент 24-25.08.2026: семь сообщений подряд без единого ответа,
    ~27 часов тишины, и разбираться пришлось месяц спустя.

    Пишем ОТДЕЛЬНОЙ сессией: та, в которой упал ход, может быть в битой
    транзакции (например Postgres оборвал соединение по
    idle_in_transaction_session_timeout), и писать в неё бессмысленно.

    Сама по себе никогда не поднимает исключение: это диагностика, она не
    вправе заменить собой исходную ошибку. Смерть процесса эта запись, конечно,
    не поймает — для неё есть сторож scripts/server/check_stalled_turns.py.
    """
    try:
        db = SessionLocal()
    except Exception:
        logger.exception("record_failed_turn: не удалось открыть сессию (user %s)", user_id)
        return
    try:
        blocks = [
            {
                "type": "text",
                "text": f"{type(error).__name__}: {str(error)[:500]}",
            }
        ]
        _save_message(db, user_id, "error", blocks, source=f"{source}_error")
        db.commit()
    except Exception:
        logger.exception("record_failed_turn: не удалось записать сбой (user %s)", user_id)
    finally:
        try:
            db.close()
        except Exception:
            pass


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
        SELECT id, role, content
        FROM agent_conversations
        WHERE user_id = :uid AND (source IS NULL OR source = 'botkinclaw')
          AND role <> 'error'
        ORDER BY id DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"uid": user_id, "lim": limit}).fetchall()
    # Быстрые записи (АД, вес, еда по кнопке, добавки) — парами «реплика →
    # ✅ записал …» с source='tracker'. Подмешиваем их в хронологию отдельным
    # лимитом, чтобы десяток записей за день не вытеснил сам разговор. Так агент
    # видит, что и когда записано, и не говорит «ты не вносил».
    min_id = min((r[0] for r in rows), default=0)
    tracker_rows = db.execute(
        text(
            """
            SELECT id, role, content
            FROM agent_conversations
            WHERE user_id = :uid AND source = 'tracker' AND id > :min_id
            ORDER BY id DESC
            LIMIT :lim
            """
        ),
        {"uid": user_id, "min_id": min_id, "lim": TRACKER_HISTORY_ROWS},
    ).fetchall()
    rows = sorted([*rows, *tracker_rows], key=lambda r: r[0])  # chronological
    rows = [(r[1], r[2]) for r in rows]
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


DIALOG_WINDOW_MINUTES = 20


def dialog_active(user_id: int, within_minutes: int = DIALOG_WINDOW_MINUTES) -> bool:
    """Идёт ли разговор с агентом: последний ответ бота — ход агента не старше окна.

    Пока разговор идёт, реплики («у меня есть квашеная капуста», «54», «позавчера»)
    уходят агенту, а не парсеру: он видит историю и знает, о чём речь.
    """
    return agent_last_turn_is_fresh(user_id, within_minutes=within_minutes)


def agent_last_turn_is_fresh(user_id: int, within_minutes: int = 10) -> bool:
    """True если ПОСЛЕДНИЙ assistant-ход у пользователя — реальный ход агента
    (source NULL/botkinclaw, не парсер-подтверждение) и он не старше within_minutes.

    Нужно, чтобы реплика-продолжение/правка («да, и утренний приём неточно…»)
    после свежего ответа агента не уходила в LLM-роутер и шаблонные ветки.
    """
    from sqlalchemy import text as sql_text
    from datetime import datetime, timezone, timedelta

    try:
        db = SessionLocal()
    except Exception:
        return False
    try:
        row = db.execute(
            sql_text(
                "SELECT source, created_at FROM agent_conversations "
                "WHERE user_id = :uid AND role = 'assistant' ORDER BY id DESC LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        if row is None:
            return False
        source, created_at = row
        if source not in (None, "botkinclaw", "e2e_test") or created_at is None:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created_at <= timedelta(minutes=within_minutes)
    except Exception:
        return False
    finally:
        db.close()


def _is_user_turn_start(m: dict) -> bool:
    """User-сообщение с реальным текстом, а не только tool_result'ы тул-цикла."""
    if m.get("role") != "user":
        return False
    content = m.get("content")
    if not isinstance(content, list):
        return True
    return any(not (isinstance(b, dict) and b.get("type") == "tool_result") for b in content)


def _validate_history(messages: list[dict]) -> list[dict]:
    """Strip orphan tool_use/tool_result blocks that violate Anthropic API.

    Bug fix for 400 'unexpected tool_use_id in tool_result blocks'. Reasons
    orphans happen at HISTORY_WINDOW boundary, after row deletions, or after
    save crashes between tool_use save and matching tool_result save.

    Algorithm:
      0. Trim the window to start at a real user turn (text, not tool_result):
         the boundary often cuts a tool loop in the middle
      1. Collect all tool_use_id present anywhere in the window
      2. Drop any tool_result blocks whose tool_use_id isn't in that set
      3. Drop any tool_use blocks whose id isn't matched by a later tool_result
      4. Drop messages that become empty after block-stripping
      5. Drop leading non-user messages; repeat 1-5 until stable — popping a
         leading assistant removes its tool_use and orphans the next
         tool_result (прецедент 28.09.2026, dev: 400 на messages.0)
    """
    start = next((i for i, m in enumerate(messages) if _is_user_turn_start(m)), 0)
    cleaned = messages[start:]
    while True:
        prev = cleaned
        cleaned = _strip_orphan_tool_blocks(cleaned)
        # Anthropic requires first message role == "user".
        while cleaned and cleaned[0]["role"] != "user":
            cleaned.pop(0)
        if cleaned == prev:
            return cleaned


def _strip_orphan_tool_blocks(messages: list[dict]) -> list[dict]:
    """One pass of steps 1-4 of _validate_history; returns a new list."""
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

    return cleaned


# ---------------------------------------------------------------------------
# P-003 — авто-инвалидация устаревших turn'ов истории при расхождении со
# свежими tool-данными текущего хода.
#
# Прецедент 09.06.2026: после фикса Z2-метрики тул отдаёт правильные числа
# (106 мин/нед, пробежка 36.7 мин), но агент продолжал парротить старые числа
# (61/38) и «Z2=0/баг» из накопленной истории, игнорируя свежий tool_result.
# Промпт-правило «свежие данные > история» (коммит ad73abf) оказалось
# недостаточным — при накопленной истории агент говорил «только что смотрел,
# ничего не изменилось» и не звал тул заново. Лечилось только ручной чисткой
# agent_conversations / командой /agent_reset.
#
# Механизм: ПЕРЕД следующим вызовом Claude сравниваем ключевые числа свежего
# tool_result этого хода с числами/утверждениями в недавних assistant-turn'ах
# и при ЯВНОМ конфликте по той же метрике нейтрализуем устаревший turn (текст
# заменяется маркером, tool_use/tool_result-блоки сохраняются — чтобы не
# нарушить парность для _validate_history).
#
# Консервативность (главный риск — выбросить валидный turn):
#  • Срабатываем только если свежий tool_result реально содержит значение по
#    этой метрике (есть ground truth этого хода).
#  • Числа из assistant-turn берём ТОЛЬКО рядом с keyword метрики и её unit.
#  • Числовой конфликт = turn содержит число по метрике, и НИ ОДНО из его
#    чисел по этой метрике не совпадает (в пределах tol) ни с одним свежим
#    значением. Если хоть одно число turn'а совпадает со свежим — turn НЕ
#    трогаем (он, видимо, обсуждает актуальное состояние / контекстуализирует).
#  • Fresh-значения собираем щедро (явные JSON-поля + числа рядом с keyword) —
#    чем больше «белый список» актуальных чисел, тем меньше ложных срабатываний.
#  • «Баг»-конфликт = в turn'е keyword + фраза вида «0/баг/не считается», а
#    свежее значение метрики строго > 0.
# См. docs/night-shift/2026-06-09.md (P-003).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StaleMetric:
    """Описание метрики, по которой ищем конфликт история↔свежий tool_result."""

    name: str
    label: str
    # keyword метрики — должен встретиться И в свежем tool-тексте, И в turn'е.
    keyword: re.Pattern
    # захват числа в контексте метрики (число + её unit). group(1) — число.
    number_re: re.Pattern
    # JSON-пути к актуальным значениям в свежем tool_result (для «белого списка»).
    # Поддержка `a.b` и `a[].b` (списки словарей).
    json_paths: tuple = ()
    abs_tol: float = 1.0  # допустимое расхождение (округление и т.п.)
    rel_tol: float = 0.0  # доп. относительный допуск от свежего значения


_NUM = r"(\d+(?:[.,]\d+)?)"
# unit-токены метрик. Z2: число + «мин» (минуты тренировки/неделю).
_RE_Z2_KW = re.compile(r"z2|зон[аеуы]\s*2|аэроб|aerobic", re.IGNORECASE)
_RE_WEIGHT_KW = re.compile(r"\bвес\b|\bweight\b|кг\b", re.IGNORECASE)
_RE_CAL_KW = re.compile(r"калор|ккал|kcal|калораж", re.IGNORECASE)
# NB: давление (систола/диастола, пара «120/80») и биомаркеры (десятки имён,
# разные единицы) — намеренно НЕ покрыты: безопасный generic-матчер для них
# заметно сложнее, а риск выкинуть валидный turn выше пользы. Follow-up — см.
# docs/night-shift/2026-06-09.md (P-003).

# Фразы «метрика сломана / ноль / не считается» — категоричные утверждения,
# которые становятся заведомо ложными, когда свежее значение метрики > 0.
_BUG_PHRASE_RE = re.compile(
    r"\bбаг\b|\bглюк|не\s+счита|не\s+работает|сломан|\b0\s*мин|\bноль\b|=\s*0\b|:\s*0\b",
    re.IGNORECASE,
)

# ⚠️ Известное ограничение (verify 09.06.2026): недельный агрегат Z2 зависит от
# окна (≈22 мин/нед за 30 дней vs 61 мин/нед за 7 дней — оба верны). Поэтому
# исторически-корректный turn про ДРУГОЕ окно может быть нейтрализован, если в
# нём нет ни одного числа, совпавшего со свежим. Вред мал (агент всё равно
# перезапрашивает тул), снижается за счёт: щедрого whitelist (per-workout
# aerobic_base_min/duration_min стабильны и не зависят от окна) + правила
# «оставить turn, если хоть одно число совпало». Follow-up — различать окна.
STALE_METRICS: tuple = (
    _StaleMetric(
        name="z2",
        label="Z2 / aerobic base (мин)",
        keyword=_RE_Z2_KW,
        number_re=re.compile(_NUM + r"\s*мин", re.IGNORECASE),
        json_paths=(
            "stats.z2_min_per_week",
            "stats.z2_target_attia",
            "stats.hiit_min_per_week",
            "items[].aerobic_base_min",
            "items[].duration_min",
        ),
        abs_tol=1.0,
    ),
    _StaleMetric(
        name="weight",
        label="вес (кг)",
        keyword=_RE_WEIGHT_KW,
        number_re=re.compile(_NUM + r"\s*кг", re.IGNORECASE),
        json_paths=("weight", "weight_kg", "latest.weight", "current.weight"),
        abs_tol=0.3,
    ),
    _StaleMetric(
        name="calories",
        label="калории (ккал)",
        keyword=_RE_CAL_KW,
        number_re=re.compile(_NUM + r"\s*к?кал", re.IGNORECASE),
        json_paths=("calories", "total_calories", "kcal", "totals.calories"),
        abs_tol=20.0,
        rel_tol=0.05,
    ),
)


def _try_json(text: str):
    """Распарсить tool_result как JSON; None если не получилось."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _to_float(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None
    return f


def _json_path_numbers(obj, path: str) -> set:
    """Числа по dot-пути. Сегмент `key[]` означает «обойти список словарей»."""
    nodes = [obj]
    for seg in path.split("."):
        list_seg = seg.endswith("[]")
        key = seg[:-2] if list_seg else seg
        nxt = []
        for node in nodes:
            if not isinstance(node, dict) or key not in node:
                continue
            val = node[key]
            if list_seg:
                if isinstance(val, list):
                    nxt.extend(val)
            else:
                nxt.append(val)
        nodes = nxt
    out: set = set()
    for n in nodes:
        f = _to_float(n)
        if f is not None:
            out.add(f)
    return out


# Сегментируем текст ТОЛЬКО по границам предложений (точка/!/?/;/перевод
# строки). НЕ дробим по « — » и « , »: «Z2-база — 61 мин/нед, пробежка 38 мин»
# должно остаться одним сегментом, иначе keyword («Z2») отрывается от числа
# («61») и теряется. Прецедент 09.06.2026 (verify): дробление по « — »/«, »
# выкидывало 61 из связки с Z2 → инвалидация срабатывала на одном «38», хотя
# 61 был актуальным числом (консервативное правило «оставить turn, если хоть
# одно число совпало со свежим» не применялось).
_SEGMENT_SPLIT_RE = re.compile(r"[\n.!?;]+")


def _numbers_near_keyword(text: str, metric: _StaleMetric) -> set:
    """Числа метрики из тех сегментов текста, где упомянут её keyword."""
    out: set = set()
    for seg in _SEGMENT_SPLIT_RE.split(text):
        if not metric.keyword.search(seg):
            continue
        for m in metric.number_re.finditer(seg):
            f = _to_float(m.group(1))
            if f is not None:
                out.add(f)
    return out


def _fresh_values(metric: _StaleMetric, tool_text: str) -> set:
    """«Белый список» актуальных значений метрики из свежего tool_result.

    Собираем щедро: явные JSON-поля + числа рядом с keyword. Чем шире набор —
    тем меньше ложных инвалидаций (assistant-число, совпавшее с любым свежим,
    считается актуальным).
    """
    vals: set = set()
    obj = _try_json(tool_text)
    if obj is not None:
        for path in metric.json_paths:
            vals |= _json_path_numbers(obj, path)
    vals |= _numbers_near_keyword(tool_text, metric)
    return vals


def _matches_fresh(value: float, fresh: set, metric: _StaleMetric) -> bool:
    """value совпадает с каким-либо свежим значением в пределах допуска."""
    for f in fresh:
        if abs(value - f) <= max(metric.abs_tol, metric.rel_tol * abs(f)):
            return True
    return False


# В маркере НЕ цитируем устаревшие числа — иначе модель может их снова
# спарротить. Конкретику (какие числа выкинули) пишем только в лог.
_STALE_MARKER = (
    "[⚠️ P-003: предыдущий ответ убран из контекста — его числа по метрике "
    "«{label}» противоречат свежему tool_result этого хода и устарели. "
    "Опирайся на свежий tool_result, не пытайся вспомнить прошлый ответ.]"
)


def _invalidate_stale_history(messages: list[dict], fresh_tool_text: str) -> list[str]:
    """Нейтрализовать assistant-turn'ы, противоречащие свежему tool_result.

    Мутирует `messages` на месте: у конфликтных assistant-turn'ов текстовые
    блоки заменяются маркером (tool_use-блоки сохраняются, чтобы не осиротить
    парные tool_result — см. _validate_history). Возвращает список лог-строк о
    том, что выкинули (пусто = ничего не тронули).

    Консервативно: см. блок-комментарий выше. Любая внутренняя ошибка
    парсинга не должна ронять ход — вызывающий оборачивает в try/except.
    """
    if not fresh_tool_text:
        return []

    # Какие метрики реально присутствуют в свежем tool_result (есть ground truth).
    active: list[tuple] = []
    for metric in STALE_METRICS:
        if not metric.keyword.search(fresh_tool_text):
            continue
        fresh = _fresh_values(metric, fresh_tool_text)
        if not fresh:
            continue
        fresh_positive = any(f > 0 for f in fresh)
        active.append((metric, fresh, fresh_positive))

    if not active:
        return []

    notes: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if not text.strip():
            continue

        for metric, fresh, fresh_positive in active:
            if not metric.keyword.search(text):
                continue

            claim_nums = _numbers_near_keyword(text, metric)
            numeric_conflict = bool(claim_nums) and all(not _matches_fresh(n, fresh, metric) for n in claim_nums)
            bug_conflict = fresh_positive and bool(_BUG_PHRASE_RE.search(text))
            # bug-фразу засчитываем только если она в сегменте с keyword метрики.
            if bug_conflict:
                bug_conflict = any(
                    metric.keyword.search(seg) and _BUG_PHRASE_RE.search(seg) for seg in _SEGMENT_SPLIT_RE.split(text)
                )

            if not (numeric_conflict or bug_conflict):
                continue

            old = ", ".join(_fmt_num(n) for n in sorted(claim_nums)) if numeric_conflict else "0/сломано"
            marker = _STALE_MARKER.format(label=metric.label)
            # Заменяем текстовые блоки маркером, tool_use оставляем.
            new_content = []
            replaced = False
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    if not replaced:
                        new_content.append({"type": "text", "text": marker})
                        replaced = True
                    # дубли text-блоков отбрасываем
                else:
                    new_content.append(b)
            if not replaced:
                new_content.insert(0, {"type": "text", "text": marker})
            msg["content"] = new_content

            notes.append(
                f"metric={metric.name} old=[{old}] fresh_sample="
                f"{sorted(fresh)[:5]} reason="
                f"{'numeric' if numeric_conflict else 'bug-phrase'}"
            )
            break  # turn нейтрализован — другие метрики по нему не проверяем

    return notes


def _fmt_num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


# ── #477: «данных нет» без единого вызова инструмента ────────────────────────
#
# Прецедент 19.09.2026: источник тренировок починили (#474), но на вопрос про
# пульс агент снова ответил «источник в DB-fallback режиме» — не вызвав ни
# одного инструмента: пересказал собственную реплику из истории, написанную до
# фикса. В промпте это прямо запрещено (UNIVERSAL_META_PROMPT), но текстовая
# директива не гарантия — проверяем факт: был ли вызов тула в этом ходе.
#
# Цена ошибки выше обычной галлюцинации: пользователь верит «данных нет» и
# перестаёт спрашивать, а баг живёт месяцами (#474 так и прожил месяц).
# Детектор намеренно узкий: ложное срабатывание не просто стоит лишнего вызова
# LLM — оно ВЫБРАСЫВАЕТ уже готовый ответ пользователя. «Не вижу поводов для
# беспокойства» или «эта функция пока недоступна» — нормальные ответы, они не
# должны попадать под гейт. Поэтому слова про отсутствие привязаны к словам про
# данные, а не ловятся сами по себе.
_UNAVAILABLE_MARKERS = re.compile(
    r"("
    # «нет данных» (без запятой между — иначе ловится «Нет, данных достаточно»)
    r"\bнет\s+(?:никаких\s+|таких\s+|полных\s+|свежих\s+)?(?:данн\w+|записей|цифр|информаци\w+)"
    # «данных (по пульсу)(у меня) нет» — только предложные вставки, иначе
    # сюда попадает «по этим данным отклонений нет» (там нет — про находку)
    r"|(?:данн\w+|записей|цифр)\s+(?:(?:по|про|за|у|в|на|от)\s+\S+\s+){0,3}"
    r"(?:пока\s+|ещё\s+|еще\s+|сейчас\s+)?нет\b"
    r"|не\s+вижу[^.!?\n]{0,20}(?:данн|записей|цифр|показател|замеров|тренировок|результат)"
    r"|(?:данн\w+|записей|цифр|тренировк\w+)[^.!?\n]{0,20}не\s+вижу"
    r"|(?:источник\w*|данн\w+|интеграци\w+|синхронизаци\w+|метрик\w+|показател\w+)"
    r"[^.!?\n]{0,20}недоступ"
    r"|недоступ\w*[^.!?\n]{0,20}(?:данн|источник|метрик|показател)"
    r"|fallback|фолбэк"
    r"|не\s+(?:могу|удалось|удаётся|удается)\s+(?:получить|посмотреть|достать|показать|найти|загрузить)"
    r"|нет\s+доступа|не\s+располагаю"
    r"|(?:данн\w+|записи\w*|информаци\w+)[^.!?\n]{0,20}отсутств"
    r"|отсутств\w+[^.!?\n]{0,20}(?:данн|записи|информаци)"
    r"|не\s+синхронизир|ничего\s+не\s+(?:нашёл|нашел|нашла|нашли)"
    r"|не\s+подтянул\w*|не\s+пришл[иа]\b"
    r")",
    re.IGNORECASE,
)

NO_TOOL_NUDGE = (
    "[Система] Ты только что сказал, что данных нет или источник недоступен, "
    "но в этом ходе не вызвал ни одного инструмента — значит, утверждение ничем "
    "не подтверждено. Вызови подходящий инструмент ПРЯМО СЕЙЧАС и ответь по его "
    "результату. Если инструмент действительно вернёт пусто — так и скажи, "
    "сославшись на него. Пользователю про эту служебную реплику не упоминай. "
    "Предыдущий черновик пользователь НЕ увидит: напиши ответ заново целиком, "
    "а не дополнение к нему."
)


# Признаки того, что инструмент САМ сообщил об отсутствии данных. Если агент
# заявляет «данных нет», а ни один tool_result этого хода пустоты не показал —
# заявление ничем не подкреплено, даже когда какой-то другой инструмент вызывался.
# Прецедент 19.09.2026 (#480/#477): на вопрос про пульс и зоны пробежки агент
# дёрнул суточные метрики (они вернулись полными), про тренировки не спросил
# вовсе — и всё равно ответил «источник тренировок в DB-fallback», пересказав
# устаревший tool_result из истории.
_EMPTY_RESULT_MARKERS = (
    '"status":"no_data"',
    '"status": "no_data"',
    '"available":false',
    '"available": false',
    '"count":0',
    '"count": 0',
    '"total_count":0',
    '"total_count": 0',
    '"items":[]',
    '"items": []',
    '"error"',
    '"source":"db"',
    '"source": "db"',
)


def tool_results_report_emptiness(results: list[str]) -> bool:
    """Хоть один инструмент этого хода вернул «пусто»/ошибку/обеднённый источник."""
    for raw in results:
        if not isinstance(raw, str):
            continue
        compact = raw.replace(" ", "")
        if any(m.replace(" ", "") in compact for m in _EMPTY_RESULT_MARKERS):
            return True
    return False


def claims_data_unavailable(text: str) -> bool:
    """Ответ заявляет, что данных нет / источник недоступен (#477)."""
    if not text:
        return False
    return bool(_UNAVAILABLE_MARKERS.search(text))


# Ложное утверждение о действии: «передал/отметил разработчикам» без вызова
# flag_for_devs в этом ходе. Ловим только прошедшее время 1-го лица; «могу
# передать», «передам», «хочешь, передам?» не срабатывают.
_DEV_FLAG_CLAIM = re.compile(
    r"\b(?:уже\s+|сразу\s+|также\s+|тоже\s+)?"
    r"(?:передал[аи]?|отметил[аи]?|сообщил[аи]?|написал[аи]?|отправил[аи]?|зафиксировал[аи]?)\s+"
    r"(?:\w+\s+){0,3}?"
    r"(?:разработчик\w*|команд\w+|александр\w*|авторам?)",
    re.IGNORECASE,
)

NO_DEV_FLAG_NUDGE = (
    "[Система] Ты утверждаешь, что передал разработчикам, но flag_for_devs не вызван: "
    "вызови его или не утверждай. Пользователю про эту служебную реплику не упоминай. "
    "Предыдущий черновик пользователь НЕ увидит: напиши ответ заново целиком."
)


def claims_dev_flag_without_tool(text: str) -> bool:
    """Ответ утверждает «передал разработчикам» (прошедшее время) — проверять
    вместе с фактом вызова flag_for_devs в этом ходе."""
    if not text:
        return False
    return bool(_DEV_FLAG_CLAIM.search(text))


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


def _end_open_tx(db) -> None:
    """Закрыть открытую транзакцию перед долгим сетевым вызовом.

    Прод-инцидент #347 (26.07.2026): ask_agent держал транзакцию открытой
    поперёк ``requests.post`` к Anthropic (до 60с на вызов), а session-level
    ``idle_in_transaction_session_timeout=15000`` (см. database/__init__.py)
    рвал такое соединение. Следующий INSERT падал с OperationalError, и
    пользователь вместо готового ответа получал «что-то сломалось». Соединение
    БЕЗ открытой транзакции этот тайм-аут не трогает.

    Транзакцию открывают не только записи: после ``db.commit()`` ORM-объект
    ``user`` истекает (expire_on_commit=True по умолчанию), и любое чтение его
    атрибута тянет refresh-SELECT — то есть снова открывает транзакцию.
    """
    try:
        db.commit()
    except Exception:
        logger.exception("agent_chat: commit перед вызовом Anthropic не удался — откатываю")
        try:
            db.rollback()
        except Exception:
            logger.exception("agent_chat: rollback после неудачного commit тоже не удался")


def _persist_turns(db, user_id: int, turns: list[tuple[str, str | list[dict]]], source: str) -> None:
    """Сохранить один или несколько turn'ов диалога ОДНОЙ транзакцией.

    #347, две задачи разом:

    1. Сбой БД не должен съедать уже готовый ответ: раньше OperationalError на
       INSERT всплывал наружу, сгенерированный (и оплаченный) ответ
       выбрасывался, пользователь видел «что-то сломалось». Теперь сбой только
       логируется.
    2. Пара ``assistant``(tool_use) + ``tool_result`` пишется атомарно. Если
       сохранить tool_use и потерять tool_result, следующий ``ask_agent``
       поднимет из БД осиротевший tool_use — Anthropic отвечает 400 на такую
       историю. ``_validate_history`` её вычистит, но вместе с контекстом того
       хода, причём молча. Атомарность убирает саму возможность рассинхрона.

    Широкий ``except Exception`` — намеренно: смысл функции в том, чтобы НИКАКОЙ
    сбой персистентности не мешал отдать оплаченный ответ. Traceback пишется в
    лог целиком, ошибка не глотается молча.
    """
    try:
        for role, content in turns:
            _save_message(db, user_id, role, content, source=source)
        db.commit()
    except Exception:
        logger.exception(
            "agent_chat: turn'ы не сохранены (roles=%s user=%s) — ответ пользователю всё равно отдаём",
            [role for role, _ in turns],
            user_id,
        )
        try:
            db.rollback()
        except Exception:
            logger.exception("agent_chat: rollback после сбоя сохранения не удался")


def log_tracker_event(user_id: int, user_text: str, confirmation: str, is_e2e: bool = False) -> None:
    """Быстрая запись мимо агента → пара ходов в его историю (source='tracker').

    Заменяет блок «последние записи» в system и #71-инъекцию АД, которую агент не
    видел (source 'bp_fast_handler' не попадал в _load_history). Ошибки глушим:
    запись в журнал уже сделана, история — вторична.
    """
    if not user_text or not confirmation:
        return
    src = "e2e_test" if is_e2e else "tracker"
    try:
        db = SessionLocal()
        try:
            _save_message(db, user_id, "user", [{"type": "text", "text": user_text}], source=src)
            _save_message(
                db,
                user_id,
                "assistant",
                [{"type": "text", "text": f"[быстрая запись, без агента] {confirmation}"}],
                source=src,
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"log_tracker_event failed for {user_id}: {e}")


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
    "get_supplement_daily_log": "💊 сверяю приём добавок по дням",
    "get_recent_bp": "🩸 поднимаю давление",
    "get_recent_glucose": "🩸 смотрю глюкозу",
    "get_glucose_stats": "🩸 считаю TIR",
    "get_daily_metrics": "📈 смотрю метрики по дням",
    "get_recent_ecg": "🫀 смотрю ЭКГ",
    "get_heart_rate_events": "🫀 смотрю события пульса",
    "get_recent_sleep": "😴 проверяю сон",
    "get_recent_trends": "📊 собираю динамику",
    "get_recent_workouts": "🏃 поднимаю тренировки",
    "get_menstrual_data": "🌸 проверяю цикл",
    "get_recent_biomarkers": "🧪 смотрю анализы",
    "get_latest_biomarkers": "🧪 проверяю свежесть анализов",
    "get_kb_value": "📋 ищу в карте здоровья",
    "list_kb_keys": "🗂 смотрю что есть в карте",
    "get_open_questions": "🚩 свеяю с открытыми вопросами",
    "get_weight_history": "⚖️ собираю историю веса",
    "get_body_measurements": "📏 проверяю замеры",
    "get_dashboard_summary": "📊 свожу метрики",
    "meal_context": "🍽 подбираю что поесть",
    "get_user_profile": "👤 читаю профиль",
    "get_user_settings": "⚙️ читаю настройки",
    "get_indoor_air": "🏠 проверяю воздух",
    "get_outdoor_weather": "🌤 смотрю погоду",
    "get_phenoage": "🧬 считаю PhenoAge",
    "get_day_summary": "📅 свожу день",
    "get_intraday_timeline": "⏱ смотрю день по часам",
    "get_profile_questionnaire": "📝 читаю анкету",
    # Write tools
    "log_meal_text": "✍️ записываю еду",
    "edit_meal": "✏️ правлю запись о еде",
    "delete_meal": "🗑 удаляю запись о еде",
    "adjust_meal_items": "📋 свожу план к факту",
    "log_supplement": "✍️ отмечаю добавку",
    "edit_supplement_log": "✏️ правлю запись о добавке",
    "log_bp": "✍️ записываю давление",
    "log_weight": "✍️ записываю вес",
    "log_workout": "✍️ записываю тренировку",
    "regenerate_health_token": "🔑 пересоздаю токен",
    "update_profile_questionnaire": "📝 обновляю анкету",
    "save_health_profile": "📝 записываю медпрофиль",
    "update_user_settings": "⚙️ обновляю настройки",
    "list_documents": "📁 смотрю документы",
    "update_document": "📁 подписываю документ",
    "send_document": "📤 присылаю документ",
    # Render tools
    "render_report": "🎨 рисую график",
    "render_chart": "🎨 рисую график",
    "generate_doctor_report": "📄 готовлю отчёт для врача",
}


def build_default_agent_prompt(user) -> str:
    """Лёгкий дефолтный per-user системный промпт для любого пользователя без
    индивидуального ``agent_system_prompt`` (само-онбординг через бота/сайт).

    Собирается из ``onboarding_data`` + полей ``users`` (имя, цель, возраст, пол),
    без вызова Claude и без PROFILE.md/KB. Никаких «семейных» привилегий — каждый
    зарегистрированный пользователь получает полный разговорный функционал (#165).
    Богатый промпт из ``onboard_family_user.py`` (если задан) имеет приоритет —
    этот билдер только fallback.
    """
    data = getattr(user, "onboarding_data", None) or {}
    name = (data.get("name") or getattr(user, "first_name", None) or "пользователь").strip() or "пользователь"
    goal = (data.get("goal") or "общее здоровье, профилактика и долголетие").strip()

    bits = []
    if data.get("age"):
        bits.append(f"{data['age']} лет")
    sex_ru = {"male": "муж.", "female": "жен."}.get(data.get("sex"))
    if sex_ru:
        bits.append(sex_ru)
    who = name + (f" ({', '.join(bits)})" if bits else "")

    # Медпрофиль приклеивается к промпту отдельным блоком (_health_profile_block).
    # Если он непустой — не утверждаем обратное строкой ниже (#340): агент верил
    # базовой фразе и советовал как здоровому, игнорируя блок с диагнозами.
    history_line = (
        "Подробной истории обследований в системе может не быть, но медицинский "
        "профиль пациента есть — он в блоке «Медпрофиль» ниже, учитывай его. "
        "Помогай освоиться и подсказывай, как пользоваться ботом, когда уместно.\n\n"
        if _has_health_profile(user)
        else "Это пользователь без подробной медицинской истории в системе — помогай "
        "освоиться и подсказывай, как пользоваться ботом, когда уместно.\n\n"
    )

    base = (
        f"Ты — личный AI-агент по теме здоровья для пользователя {name}. "
        "Часть проекта Botkin (botkin.health), канал Telegram @Botkin_md_bot.\n\n"
        "## Пользователь\n\n"
        f"**{who}.** Цель: {goal}.\n"
        f"{history_line}"
        "## Что ты умеешь и как пользователь это делает\n\n"
        "- **Логирование еды** — пользователь пишет «съел банан и кофе», шлёт фото "
        "тарелки или голосовое; ты распознаёшь и считаешь калории/БЖУ. На вопрос "
        "«как вносить еду» — объясни этими словами с примерами.\n"
        "- **Добавки и витамины** — «выпил витамин D» логируется как приём. Фото упаковки "
        "добавки распознаёт отдельный модуль (пользователь подтверждает кнопкой), сам снимок "
        "тебе не виден, но результат появляется в get_recent_supplements. При вопросах о "
        "добавках или схеме приёма СНАЧАЛА вызови get_recent_supplements и get_user_settings; "
        "не проси переписывать схему текстом, если она уже есть в данных или истории диалога.\n"
        "- **Анализы крови** — пользователь кидает PDF/фото анализов через /doc, ты разбираешь "
        "показатели. После подтверждения они попадают в динамику: видны в get_recent_biomarkers, "
        "на дашборде и в расчёте биологического возраста. Сам документ лежит в секции "
        "`documents` карты здоровья (get_kb_value).\n"
        "- **Дашборд и отчёты** — биологический возраст (PhenoAge), динамика по месяцам.\n"
        "- **Wearables и каналы данных** — реально существующие интеграции: Garmin (прямая), "
        "Apple Health (Health Auto Export или iOS Shortcut, команда /health_token), "
        "**Android Health Connect** (шаги/вес/пульс/давление/VO2; Mi Fitness, Samsung Health, "
        "Huawei Health и др. пишут в Health Connect — настройка через Александра), "
        "CGM-глюкоза FreeStyle Libre (/connect_cgm). НЕ говори, что интеграции с "
        "Google Health/Android нет — она есть через Health Connect.\n"
        "- **Вопросы о здоровье** — питание, сон, активность, корреляции в данных.\n\n"
        "## Данные пользователя — через tools\n\n"
        "Бери цифры из tools (get_recent_biomarkers, get_recent_meals, get_recent_supplements, "
        "вес/тело, сон, давление). Не угадывай. Если данных ещё нет (новый пользователь) — "
        "так и скажи и предложи начать логировать.\n"
    )

    from core.personas import get_persona

    persona = get_persona(data.get("persona"))
    tone_block = (
        "\n\n## Стиль общения\n\n"
        f"Общайся в манере «{persona.display}»: {persona.tone_prompt}.\n"
        "Это стиль, а не содержание — факты и цифры всегда бери из tools."
    )
    return base + tone_block


# users.smoking_status → человекочитаемо для промпта (#340). Курение спрашивает
# онбординг (шаг 8, нужен для PhenoAge), но до агента оно раньше не доходило:
# видели только дашборд и /user_profile.
SMOKING_RU: dict[str, str] = {
    "never": "не курит",
    "former": "бросил",
    "current": "курит",
    "occasional": "курит изредка",
}


def _has_health_profile(user) -> bool:
    """Есть ли у пользователя аллергии или хронические диагнозы в профиле.

    Курение сюда НЕ входит: оно есть почти у каждого (обязательный шаг
    онбординга) и само по себе медицинской историей не является.
    """
    from core.health.onboarding_lists import ALLERGY_KEYS, CONDITION_KEYS, onboarding_list

    data = getattr(user, "onboarding_data", None) or {}
    return bool(onboarding_list(data, ALLERGY_KEYS) or onboarding_list(data, CONDITION_KEYS))


def _health_profile_block(user) -> str:
    """Живой блок медпрофиля (аллергии/диагнозы/курение) для промпта.

    Пусто по всем источникам → пустая строка (не шумим). Аллергии и диагнозы
    читаются из тех же ключей ``onboarding_data``, куда пишет
    merge_onboarding_lists, поэтому агент видит свежие данные сразу после
    /doc-сохранения (промпт пересобирается на каждый вызов ask_agent).
    Курение — из ``users.smoking_status``.
    """
    from core.health.onboarding_lists import ALLERGY_KEYS, CONDITION_KEYS, onboarding_list

    data = getattr(user, "onboarding_data", None) or {}
    allergies = onboarding_list(data, ALLERGY_KEYS)
    conditions = onboarding_list(data, CONDITION_KEYS)
    smoking = SMOKING_RU.get(getattr(user, "smoking_status", None) or "")
    if not allergies and not conditions and not smoking:
        return ""
    lines = ["\n\n## Медпрофиль (со слов пациента / из документов)"]
    if allergies:
        lines.append(f"Аллергии: {', '.join(allergies)}")
    if conditions:
        lines.append(f"Хронические диагнозы: {', '.join(conditions)}")
    if smoking:
        lines.append(f"Курение: {smoking}")
    lines.append("Учитывай при советах (лекарства, продукты, триггеры).")
    return "\n".join(lines)


def _genetics_prompt_block(user) -> str:
    """Блок ДНК-теста для промпта. Пусто, если теста у пользователя нет.

    Вынесено в core.health.genetics: генетика касается почти любой темы, и
    перечислять их правилами оказалось тупиком (см. историю в модуле). Блок
    стабилен per-user, поэтому идёт в кэшируемую часть промпта рядом с
    медпрофилем и кэш на каждом сообщении не инвалидирует.
    """
    try:
        from core.health.genetics import genetics_prompt_block

        return genetics_prompt_block(user)
    except Exception:
        logger.exception("agent_chat: не удалось собрать блок генетики — отвечаем без него")
        return ""


def _health_profile_ask_block(user) -> str:
    """Мягкий сбор медпрофиля: инструкция спросить ОДИН раз (#340).

    Онбординг-квиз про хроники и постоянные лекарства не спрашивает (шаг убран
    в f366c98 ради короткого квиза), а у самозарегистрированного юзера нет ни
    KB, ни документов — медконтекста нет вообще. Поэтому просим агента добрать
    это в диалоге, но ровно один раз: после ответа он зовёт save_health_profile,
    который ставит ``health_profile_asked``.

    Пустая строка, если профиль уже есть, вопрос уже задавали или у юзера
    задан индивидуальный ``agent_system_prompt``: такой промпт собран из
    PROFILE.md/KB (onboard_family_user.py), медистория там уже подробная —
    спрашивать про хроники значит переспрашивать то, что агент и так знает.
    """
    data = getattr(user, "onboarding_data", None) or {}
    if (getattr(user, "agent_system_prompt", None) or "").strip():
        return ""
    if data.get("health_profile_asked") or _has_health_profile(user):
        return ""
    return (
        "\n\n## Медпрофиль ещё не собран\n"
        "Про хронические болячки и постоянные лекарства пользователя мы не знаем — "
        "онбординг об этом не спрашивает. Спроси ОДИН раз, мягко и к месту (когда "
        "разговор и так про здоровье, самочувствие, еду или анализы). Не начинай с "
        "этого диалог, не повторяй вопрос в каждом ответе и не превращай его в анкету. "
        "Что услышал — сохрани через save_health_profile. Если человеку нечего "
        "сообщить или он не хочет отвечать — вызови save_health_profile с "
        "nothing_to_report=true и больше не спрашивай."
    )


# Admin-контекст-блок системного промпта (#337). Admin-статус (BOTKIN_ADMIN_IDS) —
# отдельная ось от когорты данных (owner/family/…): когорта ограничивает видимость
# чужих данных, admin-статус даёт право на операционные действия. Без явного сигнала
# LLM гадает по family-персоне и отказывает админу в триаже фидбека.
ADMIN_CONTEXT_PROMPT = (
    "# 🛡 ТЫ ОБЩАЕШЬСЯ С АДМИНИСТРАТОРОМ BOTKIN\n"
    "\n"
    "Текущий пользователь — администратор системы (входит в BOTKIN_ADMIN_IDS). Его\n"
    "admin-статус НЕ зависит от когорты данных (owner/family/early_user/external):\n"
    "когорта ограничивает видимость чужих данных, а admin-статус даёт право на\n"
    "операционные действия с ботом.\n"
    "\n"
    "Поэтому: если админ просит показать очередь обратной связи или разобрать обращение\n"
    "(сменить статус/приоритет, ответить автору) — ВЫЗОВИ `list_feedback` / `triage_feedback`\n"
    "и выполни. НЕ отказывай со ссылкой на когорту («ты family-пользователь») — эти\n"
    "инструменты доступны тебе именно потому, что пользователь администратор.\n"
    "\n"
    "---\n"
    "\n"
)


def build_admin_context(is_admin: bool) -> str:
    """Admin-контекст-блок для системного промпта агента (#337).

    Пустая строка для обычных пользователей. Для админов — явный сигнал, что
    admin-статус (BOTKIN_ADMIN_IDS) — отдельная ось от когорты данных, чтобы LLM
    не отказывал в триаже фидбека, приняв себя за «family-only» ассистента.
    """
    return ADMIN_CONTEXT_PROMPT if is_admin else ""


def _log_first_question(db, user_id: int, is_e2e: bool) -> None:
    """E6: первое свободное сообщение агенту (once). Пропускаем E2E-прогоны."""
    if is_e2e:
        return
    try:
        log_event(db, user_id=user_id, event="first_agent_question", once=True)
    except Exception:
        logger.exception("E6 first_agent_question log failed for %s", user_id)


def ask_agent(
    user_id: int,
    user_text: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    is_e2e: bool = False,
    meal_preview_sink: Optional[list] = None,
    images: Optional[list] = None,
) -> str:
    """Synchronous — call from `run_in_executor`. См. :func:`_ask_agent_impl`.

    Обёртка ставит RLS-контекст (ADR-0014) на весь ход агента и снимает его на
    выходе: executor-потоки переиспользуются, контекст не должен утечь к
    следующей задаче в этом потоке.
    """
    with user_context(user_id):
        return _ask_agent_impl(
            user_id,
            user_text,
            progress_cb=progress_cb,
            is_e2e=is_e2e,
            meal_preview_sink=meal_preview_sink,
            images=images,
        )


def _ask_agent_impl(
    user_id: int,
    user_text: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    is_e2e: bool = False,
    meal_preview_sink: Optional[list] = None,
    images: Optional[list] = None,
) -> str:
    """Synchronous — call from `run_in_executor`.

    meal_preview_sink: если передан (чат в боте), `log_meal_text` не пишет в БД,
    а кладёт сюда черновик — бот покажет ту же карточку «Сохранить/Отмена», что и
    у быстрого пути. Без sink (MCP, проактивные вызовы) запись идёт сразу.

    images: пути к фото (скрин Garmin/Apple Health и т.п.) — уходят модели
    картинкой в текущем ходе. В историю пишется только текст: base64 в
    agent_conversations раздул бы каждый следующий ход.

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
    # RLS (ADR-0014): ask_agent синхронный и зовётся из executor-потока —
    # привязываем сессию и contextvar потока к пользователю явно, не полагаясь
    # на то, что вызывающий скопировал контекст.
    bind_user(db, user_id)
    try:
        user = db.query(User).filter_by(telegram_id=user_id).first()
        if not user or not user.is_active:
            raise RuntimeError(f"User {user_id} not found or inactive")

        _log_first_question(db, user_id, is_e2e)

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
        # P-003: всё ДО текущего user-сообщения — кандидаты на инвалидацию, если
        # свежий tool_result этого хода им противоречит (см. _invalidate_stale_history).
        prior_history_len = len(history)
        user_content = _user_content_with_images(user_text, images)
        history.append({"role": "user", "content": user_content})

        # Persist user turn immediately so a crash mid-call doesn't lose it.
        # Намеренно НЕ через _persist_turns: тут сбой БД должен всплыть наружу.
        # Ответа ещё нет (сеть даже не тронута), терять нечего, а работать
        # дальше с мёртвой БД смысла нет — tools всё равно не ответят.
        _save_message(db, user_id, "user", user_text, source=src)
        db.commit()

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        # Семейный override (onboard_family_user.py) приоритетен; иначе — лёгкий
        # дефолт, чтобы разговорный агент работал у любого пользователя (#165).
        per_user_prompt = (user.agent_system_prompt or "").strip() or build_default_agent_prompt(user)
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
            "«позавчера», «на той неделе» считай строго от этой даты. "
            "Текущее время дня приходит отдельным системным блоком «⏰ Сейчас…» — "
            "на любой вопрос о текущем времени/«сейчас» отвечай ТОЛЬКО по нему; "
            "упоминания времени в сообщениях пользователя из истории устарели.\n"
            "Это касается ЛЮБОГО инструмента записи данных (давление, добавки, "
            "тренировки, еда и т.д.): если пользователь упомянул прошлое — либо "
            "вычисли и передай дату/время явно, либо переспроси; молчаливая запись "
            "«на сейчас» при явном упоминании прошлого недопустима.\n\n"
        )
        from config.users import is_admin as _is_admin

        # #337: сообщаем LLM об admin-статусе явно (иначе гадает по когорте и
        # отказывает админу в триаже фидбека). Блок стабилен per-user → в
        # кэшируемой части промпта, кэш не инвалидируется.
        merged_system_prompt = (
            _date_line
            + UNIVERSAL_META_PROMPT
            + per_user_prompt
            + _health_profile_block(user)
            + _genetics_prompt_block(user)
            + _health_profile_ask_block(user)
            + build_admin_context(_is_admin(user_id))
        )
        # Tracker-события (вес/еда/АД из парсеров) меняются КАЖДОЕ сообщение —
        # держим их ОТДЕЛЬНЫМ system-блоком БЕЗ cache_control, чтобы не
        # инвалидировать кэш стабильного промпта на каждый ход (#169 ревью).
        # ⏰ Текущее время юзера — тоже сюда (F-004, 02.07.2026): в кэшируемой
        # _date_line время нельзя (инвалидация кэша каждый ход), а без него агент
        # не знает время суток и путает «сегодня/вчера» при данных за days=1.
        _time_line = (
            f"⏰ Сейчас у пользователя {_now_local.strftime('%H:%M')} ({_tz_name}). "
            "Это ЕДИНСТВЕННЫЙ достоверный источник текущего времени: любые упоминания "
            "времени/«сейчас» в истории диалога относятся к моменту тех сообщений и УСТАРЕЛИ.\n"
        )
        tracker_block = _time_line
        # #269: триаж-тулы инбокса — только админам; остальные их не видят.
        _admin_only = {"list_feedback", "triage_feedback"}
        _tool_defs = TOOLS if _is_admin(user_id) else [t for t in TOOLS if t["name"] not in _admin_only]
        cached_tools = [dict(t) for t in _tool_defs]
        # breakpoint на последнем инструменте кеширует все схемы инструментов
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
        # Prompt caching давно GA — beta-хедер prompt-caching-2024-07-31 не нужен
        request_headers = dict(headers)

        # #477: факт вызова инструмента в этом ходе и одноразовость нуджа.
        # Нудж одноразовый (nudged не сбрасывается), поэтому лишний раунд к
        # лимиту MAX_TOOL_ITERATIONS добавляется максимум один.
        tool_called_this_turn = False
        nudged = False
        # Пустой финальный ход (только пустой thinking, без текста) — повторяем
        # один раз. E2E на деве 01.11.2026: на «или лимонады — в них же сахар»
        # модель вернула один пустой thinking-блок, пользователь получил
        # «нет внятного ответа».
        empty_retried = False
        tools_called_this_turn: set[str] = set()
        # Тексты всех tool_result этого хода — по ним проверяем, подкреплено ли
        # заявление «данных нет» (см. tool_results_report_emptiness).
        turn_tool_result_texts: list[str] = []

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
                ]
                + ([{"type": "text", "text": tracker_block}] if tracker_block else []),
                "tools": cached_tools,
                "messages": history,
                # Автокеш хвоста: итерации цикла инструментов читают историю и
                # прошлые tool_result из кеша, а не шлют их заново по полной цене.
                "cache_control": {"type": "ephemeral"},
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
                # #347: закрываем транзакцию ДО сети. Внутри этого хелпера БД
                # не трогаем, поэтому одного вызова хватает на все три post'а
                # (основной + retry + fallback).
                _end_open_tx(db)
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
                history = [{"role": "user", "content": user_content}]
                payload["messages"] = history
                r = _post_with_overload_retry(payload)
            if r.status_code >= 400 and "credit balance" in r.text.lower():
                from core.infra.owner_alerts import notify_owner_low_anthropic_balance

                notify_owner_low_anthropic_balance()
            r.raise_for_status()
            response = r.json()

            # Best-effort usage logging — never blocks
            try:
                from core.llm_usage import log_anthropic_response

                log_anthropic_response(
                    purpose=("agent_chat_nudge" if nudged else ("agent_chat_tool" if iteration > 0 else "agent_chat")),
                    model=MODEL,
                    response_json=response,
                    user_id=user_id,
                )
            except Exception:
                logger.exception("agent_chat: usage logging failed")

            stop_reason = response.get("stop_reason")
            blocks = response.get("content", [])

            if stop_reason == "tool_use":
                tool_called_this_turn = True
                # Record assistant turn (text + tool_use blocks) в память сразу,
                # в БД — ниже, одной транзакцией вместе с tool_result (#347):
                # осиротевший tool_use в истории ломает следующий ход.
                history.append({"role": "assistant", "content": blocks})

                # Прогресс по tools этого turn'a. Если в одном turn модель
                # просит несколько tools (типично — get_weight + get_trends)
                # — берём label первого render-tool если он есть, иначе
                # первого read/write tool. render имеет приоритет потому что
                # это самая «зрелищная» операция.
                if progress_cb:
                    tool_names = [b["name"] for b in blocks if b.get("type") == "tool_use"]
                    render_tools = [
                        n for n in tool_names if n in ("render_chart", "render_report", "generate_doctor_report")
                    ]
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
                    tools_called_this_turn.add(name)
                    if name == "log_meal_text" and meal_preview_sink is not None:
                        result_text = _preview_meal_text(user_id, args, meal_preview_sink)
                    else:
                        result_text = _call_tool(name, args, token)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": result_text,
                        }
                    )

                # P-003: свежие tool_result этого хода — ground truth. Сверяем
                # ключевые числа с недавними assistant-turn'ами истории и
                # нейтрализуем те, что противоречат (иначе агент парротит старое
                # вместо свежего — прецедент 09.06.2026, F-001). Мутирует turn'ы
                # in-place → следующая итерация увидит чистую историю.
                # Выключено по умолчанию (аудит обвязки, ноябрь 2026): за 05.09–01.11
                # на проде 7 срабатываний из ~380 вызовов инструментов, все по Z2 с
                # разными окнами (35 → «свежее» 67) — ложные. Включить: env
                # AGENT_STALE_HISTORY_GUARD=1. Удалить, если не понадобится.
                if STALE_HISTORY_GUARD:
                    try:
                        fresh_text = "\n".join(
                            tr["content"] for tr in tool_results if isinstance(tr.get("content"), str)
                        )
                        stale_notes = _invalidate_stale_history(history[:prior_history_len], fresh_text)
                        for note in stale_notes:
                            logger.info("P-003 invalidated stale turn: user=%s %s", user_id, note)
                    except Exception:
                        logger.exception("P-003 stale-history invalidation failed (non-fatal)")

                # tool_use + tool_result — одной транзакцией (см. _persist_turns).
                turn_tool_result_texts.extend(
                    tr["content"] for tr in tool_results if isinstance(tr.get("content"), str)
                )
                _persist_turns(db, user_id, [("assistant", blocks), ("tool_result", tool_results)], src)
                history.append({"role": "user", "content": tool_results})
                continue  # next iteration — model will incorporate tool results

            # stop_reason in ("end_turn", "max_tokens", "stop_sequence") — final.
            text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
            reply_text = "\n".join(text_parts).strip()

            if not reply_text and not empty_retried:
                empty_retried = True
                logger.warning("agent_chat: пустой финальный ход — повтор (user=%s)", user_id)
                continue

            # 🚦 #477: «данных нет», а инструмент ни разу не вызван — утверждение
            # ничем не подтверждено. Толкаем модель в тул ОДИН раз и НЕ сохраняем
            # отбракованный ответ: попав в историю, он поедет дальше как факт
            # (ровно так «DB-fallback» пережил фикс источника #474).
            claim_unsupported = not tool_results_report_emptiness(turn_tool_result_texts)
            if not nudged and claim_unsupported and claims_data_unavailable(reply_text):
                nudged = True
                logger.warning(
                    "agent_chat: «данных нет» без вызова инструмента — нудж (user=%s): %.120s",
                    user_id,
                    reply_text.replace("\n", " "),
                )
                # Пишем отбракованный ответ под отдельным source: `_load_history`
                # берёт только `botkinclaw`, поэтому в контекст модели он не
                # вернётся, но останется видимым для ночного review-conversations
                # и для настройки детектора по реальным срабатываниям.
                _persist_turns(db, user_id, [("assistant", blocks)], f"{src}_nudged")
                if progress_cb:
                    try:
                        progress_cb("🔄 перепроверяю данные")
                    except Exception:
                        logger.exception("progress_cb nudge failed")
                history.append({"role": "assistant", "content": blocks})
                history.append({"role": "user", "content": NO_TOOL_NUDGE})
                continue

            # Ложное «передал разработчикам» без вызова flag_for_devs. Делит
            # одноразовый флаг nudged с #477: два нуджа подряд и цикл невозможны.
            if (
                not nudged
                and "flag_for_devs" not in tools_called_this_turn
                and claims_dev_flag_without_tool(reply_text)
            ):
                nudged = True
                logger.warning(
                    "agent_chat: «передал разработчикам» без flag_for_devs — нудж (user=%s): %.120s",
                    user_id,
                    reply_text.replace("\n", " "),
                )
                _persist_turns(db, user_id, [("assistant", blocks)], f"{src}_nudged")
                history.append({"role": "assistant", "content": blocks})
                history.append({"role": "user", "content": NO_DEV_FLAG_NUDGE})
                continue

            # #347: ответ уже сгенерирован и оплачен — сбой записи в историю
            # его не отменяет, отдаём пользователю в любом случае.
            _persist_turns(db, user_id, [("assistant", blocks)], src)

            return reply_text

        # Exhausted iterations
        logger.warning("agent_chat: max iterations (%s) hit", MAX_TOOL_ITERATIONS)
        return "Не справился за разумное число шагов — попробуй переформулировать вопрос."
    except BaseException as e:
        # BaseException, а не Exception: отмена задачи (CancelledError) — как раз
        # тот случай, когда хендлер до своей ветки `except` уже не доберётся и
        # пользователь не увидит ничего. Такой ход обязан остаться в данных.
        record_failed_turn(user_id, e, source=src)
        raise
    finally:
        db.close()
