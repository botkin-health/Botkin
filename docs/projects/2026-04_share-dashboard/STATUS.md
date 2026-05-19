# Share Dashboard

**Status:** 🟢 COMPLETED
**Started:** 2026-04-23
**Owner:** Александр Лысковский
**Cohort:** all

## Цель

Каждый пользователь может сгенерировать секретную ссылку `https://health.orangegate.cc/mc/{share_token}` на свой персональный дашборд здоровья и поделиться ею с друзьями.

## Что сделано

- Колонка `users.share_token` (UUID v4), команда `/share` в боте генерирует и присылает URL
- FastAPI render-on-the-fly в `apple_health.py` — данные всегда свежие
- Сброс токена → старая ссылка перестаёт работать (security by obscurity)

## Связи

- SPEC.md / PLAN.md
