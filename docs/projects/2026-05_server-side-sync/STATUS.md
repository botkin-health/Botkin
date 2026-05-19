# Server-side sync (Phase 1-6)

**Status:** 🟢 COMPLETED
**Started:** 2026-05-17
**Completed:** 2026-05-19
**Owner:** Александр Лысковский
**Cohort:** owner (cron на сервере, affects всех пользователей косвенно)

## Цель

Перенести 4 pull-источника данных (Garmin, Netatmo, Weather, Zepp) с локального Mac на сервер. Mac остаётся для аналитики (зеркалирует данные обратно). На сервере — единый cron `sync_all.sh` в 04:05 UTC. В боте появляется `/sync` команда для триггера вручную.

## Что сделано

| Phase | Что | PR |
|---|---|---|
| 1 | Weather на сервере | #6 |
| 2 | Netatmo на сервере | #6 |
| 3 | Zepp direct API mode (ждёт reauth токена) | #6 |
| 4 | Garmin на сервере | #6 |
| 5 | Cron consolidate → `scripts/server/sync_all.sh` | #9 |
| 6 | Disable Mac launchd | (не нужно — уже было отключено) |
| Bonus | `/sync` команда в боте + bind-mounts всех .py-папок | #6, #7 |
| Hotfix | `lnetatmo` в requirements + port 8081 в compose | #8, #12 |

## На проде сейчас

```
04:05 UTC  docker exec healthvault_bot bash /app/scripts/server/sync_all.sh
           → weather (1с) + netatmo (1с) + garmin (14с)
           → один лог /var/log/botkin_sync.log
```

## Связи

- Коммиты в main: be759a0, 87a15e6, 8ef847c, af072fa, 3bd5dc4
- ROADMAP DONE: «17–19 мая (server-side sync)»

## Tech debt после

- **Zepp reauth** требует ручного шага раз в ~5-7 дней (OAuth через Xiaomi). Отложено.
- **/sync для не-admin** требует per-user creds в БД — следующий проект.
