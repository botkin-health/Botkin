# Telegram Mini App — Settings Panel

**Status:** 🟢 COMPLETED
**Started:** 2026-04-05
**Owner:** Александр Лысковский
**Cohort:** all

## Цель

Дать каждому юзеру панель настроек в Telegram Mini App: список добавок, отображение калорий, нотификации — без правки кода.

## Что сделано

- Таблица `user_settings` в PostgreSQL + CRUD
- FastAPI `/api/settings` в `apple_health.py`
- SPA `webapp/index.html` с Telegram WebApp auth (HMAC-SHA256)
- `SupplementService` рефакторнут: читает из БД, а не из хардкода

## Tech debt

- **Supplement reminders (APScheduler)** — UI toggle saves в БД, но реальный scheduling — v2 (помечено "скоро"). См. `todo.md`.

## Связи

- PLAN.md — пошаговый план реализации
