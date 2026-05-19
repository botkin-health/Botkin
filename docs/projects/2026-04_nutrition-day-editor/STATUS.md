# Nutrition Day Editor

**Status:** 🟢 COMPLETED
**Started:** 2026-04-17
**Owner:** Александр Лысковский
**Cohort:** all

## Цель

Дать возможность просматривать и редактировать любой день питания прямо из Telegram Mini App — без открытия БД.

## Что сделано

- `telegram-bot/webhook/nutrition_api.py` — FastAPI APIRouter, mounted в apple_health webhook app (port 8081)
- Pure-function slot-mapping (завтрак/обед/перекус/ужин)
- Расширение `webapp/index.html` — секция «Дневник» как дефолтная, настройки за ⚙️
- Edit weight с пропорциональным KBJU scaling, delete с undo
- LLM-resolved добавление продуктов через favorites или manual entry
- Sticky прогресс-бары в футере против дневных целей

## Связи

- SPEC.md / PLAN.md
