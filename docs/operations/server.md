# Сервер Botkin (прод)

> Снимок на 2026-06-13. Hetzner, единый хост (пока и прод, и будущий dev на одной машине).

## Доступ

```bash
ssh botkin_server          # алиас в ~/.ssh/config (User igorn, key ~/.ssh/botkin/botkin_igorn)
# напрямую:
ssh -i ~/.ssh/botkin/botkin_igorn igorn@116.203.213.137
```

Пользователь `igorn` — в группах `sudo` и `docker` (деплой без root-пароля).

## Железо / ОС

| | |
|---|---|
| IP | `116.203.213.137` |
| ОС | Ubuntu 24.04 LTS (kernel 6.8) |
| CPU | 2 vCPU Intel Xeon (Skylake) |
| RAM | 3.7 GB (+ 4 GB swap) |
| Диск | 38 GB SSD (~14 GB свободно) |
| Docker | 29.x + compose v5 |

## Footprint Botkin

| Что | Где / как |
|---|---|
| Бот | контейнер `healthvault_bot` (FastAPI :8081, healthy) |
| БД | контейнер `healthvault_postgres` (postgres:15, volume) |
| Код (текущая модель) | `/opt/healthvault` — rsync + `docker compose build` на сервере (см. `deploy.sh`) |
| Бэкапы | `/opt/backups` — nightly `pg_dump` (cron), **root-only** |
| Ingress | **nginx на хосте** терминирует TLS для `health.orangegate.cc` → `127.0.0.1:8081` |

Целевая pull-only модель кладёт стек в `/opt/botkin` (см. `docker-compose.prod.yml`,
`.github/workflows/deploy-prod.yml`).

## ⚠️ Важно: хост общий (multi-tenant)

На машине крутятся и **другие, не связанные с Botkin, стеки** (включая отдельный
LLM-proxy на `127.0.0.1:4000`). Отсюда правила для деплоя Botkin:

- Чистка образов — **только** `ghcr.io/botkin-health/botkin-bot` (никаких `prune -af`).
- **nginx на хосте занимает порты 80/443** и обслуживает несколько vhost'ов. Перевод
  Botkin на Caddy — это НЕ drop-in: Caddy не сможет co-bind 443, пока там nginx.
  Варианты: (а) оставить nginx и для Botkin; (б) мигрировать все vhost'ы на Caddy
  (трогает другие проекты). Решение — открытый вопрос, см. ROADMAP/issue.
- Деплой не трогает контейнеры/volume/образы других стеков.
