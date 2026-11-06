#!/usr/bin/env python3
"""Botkin MCP-коннектор для Claude Desktop (#228).

stdio-сервер, который Claude Desktop пользователя запускает из .mcpb-бандла.
Достаёт durable PAT (env BOTKIN_PAT, из keychain через user_config) и хост API
(env BOTKIN_API_BASE), обменивает PAT→JWT и проксирует вызовы в /api/agent/*.

Инструменты — тонкие обёртки над серверными эндпоинтами (вся логика, RLS и
enforcement прав ro/rw — на сервере). ro-токен на write-инструменте получит 403.

Гибридная приватность: ЛОКАЛЬНЫЕ файлы пользователя (КПТ-дневник, сканы анализов)
этот коннектор НЕ читает — это работа встроенного в Claude Desktop коннектора
файловой системы. Botkin отдаёт только серверные данные.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

# .mcpb запускает скрипт по абсолютному пути — кладём его директорию в sys.path,
# чтобы найти соседний botkin_client.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botkin_client import BotkinClient  # noqa: E402

BASE_URL = os.getenv("BOTKIN_API_BASE", "https://botkin.health")
PAT = os.getenv("BOTKIN_PAT", "")

mcp = FastMCP("Botkin")
_client = BotkinClient(BASE_URL, PAT) if PAT else None
if _client is None:
    print(
        "Botkin MCP: BOTKIN_PAT не задан. Выпусти токен в боте: /connect_mcp",
        file=sys.stderr,
    )


def _api() -> BotkinClient:
    if _client is None:
        raise RuntimeError("Не задан BOTKIN_PAT. Выпусти токен в боте Botkin: /connect_mcp")
    return _client


# ── Чтение (доступно и ro-, и rw-токену) ──────────────────────────────────────


@mcp.tool()
def get_day_summary(date: str) -> Any:
    """Сводка за день: питание, активность, замеры. date — YYYY-MM-DD."""
    return _api().get("/api/agent/day_summary", date=date)


@mcp.tool()
def get_recent_meals(days: int = 7, compact: bool = False, daily: bool = False) -> Any:
    """Питание за последние `days` дней (1..366).

    До 14 дней — приёмы пищи целиком (продукты, КБЖУ). 15–90 дней — compact (имена продуктов + ккал).
    daily=True — по дням: число приёмов, ккал, белки, жиры, углеводы, клетчатка (только съеденное);
    при days > 90 включается сам — так смотреть тренды за полгода/год одним вызовом."""
    return _api().get("/api/agent/recent_meals", days=days, compact=compact or None, daily=daily or None)


@mcp.tool()
def get_recent_biomarkers(limit: int = 20) -> Any:
    """Последние биомаркеры из анализов крови (до `limit` записей)."""
    return _api().get("/api/agent/recent_biomarkers", limit=limit)


@mcp.tool()
def get_weight_history(days: Optional[int] = None, series: bool = False) -> Any:
    """История веса. days=None — вся; series=True — временной ряд для графика."""
    return _api().get("/api/agent/weight_history", days=days, series=series)


@mcp.tool()
def get_recent_workouts(days: int = 30) -> Any:
    """Тренировки за последние `days` дней."""
    return _api().get("/api/agent/recent_workouts", days=days)


@mcp.tool()
def get_recent_bp(days: int = 14) -> Any:
    """Измерения артериального давления за последние `days` дней (максимум 90, больше — обрезается до 90)."""
    return _api().get("/api/agent/recent_bp", days=days)


@mcp.tool()
def get_user_profile() -> Any:
    """Профиль пользователя: имя, пол, рост, дата рождения, часовой пояс."""
    return _api().get("/api/agent/user_profile")


@mcp.tool()
def get_user_settings() -> Any:
    """Цели и настройки: целевой вес и дата, режим калорий, BMR, схема добавок, напоминания."""
    return _api().get("/api/agent/user_settings")


@mcp.tool()
def get_dashboard_summary() -> Any:
    """Сводка за последние 7 дней: средние шаги, пульс, съеденные калории, последний вес."""
    return _api().get("/api/agent/dashboard_summary")


@mcp.tool()
def get_recent_sleep(days: int = 14) -> Any:
    """Сон за последние `days` дней (максимум 90): длительность, оценка сна, глубокий/REM."""
    return _api().get("/api/agent/recent_sleep", days=days)


@mcp.tool()
def get_daily_metrics(days: int = 14) -> Any:
    """По дням (до 180) из Apple Health: сатурация, VO2max, дыхание, температура запястья, min/max пульса,
    фазы сна, походка, этажи. `available` — по скольким дням метрика реально пришла."""
    return _api().get("/api/agent/daily_metrics", days=days)


@mcp.tool()
def get_recent_trends(days: int = 14, full_series: bool = False) -> Any:
    """По дням: HRV, Body Battery, стресс, шаги, был ли алкоголь. Для вопросов «падает ли HRV»,
    «когда стресс выше». full_series=True — весь ряд без прореживания."""
    return _api().get("/api/agent/recent_trends", days=days, full_series=full_series or None)


@mcp.tool()
def get_recent_supplements(days: int = 30) -> Any:
    """Добавки за последние `days` дней: по каждой — сколько дней принималась, последний приём и дозировка."""
    return _api().get("/api/agent/recent_supplements", days=days)


@mcp.tool()
def get_glucose_stats(days: int = 7) -> Any:
    """Глюкоза с CGM за `days` дней (1..90): среднее, вариабельность, время в диапазоне."""
    return _api().get("/api/agent/glucose_stats", days=days)


@mcp.tool()
def get_latest_biomarkers() -> Any:
    """Последнее значение каждого биомаркера из анализов + насколько оно устарело."""
    return _api().get("/api/agent/latest_biomarkers")


@mcp.tool()
def get_body_measurements() -> Any:
    """Антропометрия: талия, шея, бёдра, грудь, бедро, бицепс (см), сила хвата (кг)."""
    return _api().get("/api/agent/body_measurements")


@mcp.tool()
def get_menstrual_data(months: int = 6) -> Any:
    """Менструальный цикл за `months` месяцев (до 24): записи flow и рассчитанные длины циклов."""
    return _api().get("/api/agent/menstrual_data", months=months)


@mcp.tool()
def list_documents() -> Any:
    """Документы профиля (загруженные анализы через /doc в боте, полисы, справки): id, название, дата."""
    return _api().get("/api/agent/list_documents")


@mcp.tool()
def botkin_api(method: str, path: str, params: Optional[dict] = None) -> Any:
    """Низкоуровневый вызов любого эндпоинта Botkin /api/agent/*.

    Escape-hatch для эндпоинтов без отдельной обёртки. method — GET/POST,
    path — например '/api/agent/phenoage', params — query (GET) или тело (POST).
    Прочие GET без обёрток: /api/agent/phenoage (биологический возраст),
    /api/agent/recent_glucose?hours=24, /api/agent/recent_ecg, /api/agent/heart_rate_events,
    /api/agent/intraday?date=YYYY-MM-DD, /api/agent/supplement_daily_log, /api/agent/kb_value?key=...,
    /api/agent/list_kb_keys, /api/agent/open_questions, /api/agent/outdoor_weather, /api/agent/indoor_air.
    Сервер сам проверит права: write по ro-токену вернёт ошибку.
    """
    method = method.upper()
    if method == "GET":
        return _api().request("GET", path, params=params or None)
    return _api().request(method, path, json_body=params or {})


# ── Запись (требует rw-токен; ro вернёт понятную ошибку 403) ───────────────────


@mcp.tool()
def log_meal_text(text: str, date: Optional[str] = None, slot: Optional[str] = None) -> Any:
    """Записать приём пищи свободным текстом. date — YYYY-MM-DD (по умолч. сегодня),
    slot — breakfast|lunch|dinner|snack (по умолч. авто). Требует rw-токен."""
    payload: dict = {"text": text}
    if date:
        payload["date"] = date
    if slot:
        payload["slot"] = slot
    return _api().post("/api/agent/log_meal_text", payload)


@mcp.tool()
def log_bp(systolic: int, diastolic: int, pulse: Optional[int] = None, measured_at: Optional[str] = None) -> Any:
    """Записать артериальное давление (мм рт.ст.) и пульс. measured_at — ISO-дата
    (по умолч. сейчас). Требует rw-токен."""
    payload: dict = {"systolic": systolic, "diastolic": diastolic}
    if pulse is not None:
        payload["pulse"] = pulse
    if measured_at:
        payload["measured_at"] = measured_at
    return _api().post("/api/agent/log_bp", payload)


if __name__ == "__main__":
    mcp.run()
