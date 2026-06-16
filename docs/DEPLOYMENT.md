# Руководство по развёртыванию

**Деплой — только через GitHub Actions.** Shell-скриптов (`deploy.sh` и т.п.) больше нет.
Workflow «Deploy prod» собирает Docker-образ бота, пушит его в GHCR и по SSH тянет
образ на сервере (pull-only — сборки на сервере нет).

---

## Как запустить деплой

**Через UI:** GitHub → Actions → «Deploy prod» → **Run workflow**.

**Через CLI:**
```bash
gh workflow run deploy-prod.yml -f branch=main
```

### Параметры workflow

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `branch` | `main` | Ветка/тег/SHA, из которой собирается образ и берётся `docker-compose.prod.yml` |
| `image_tag` | `""` (пусто) | Готовый тег образа для **отката**. Если задан — сборка пропускается, деплоится указанный образ |

## Что делает workflow

1. **Build** (если `image_tag` пуст): собирает Docker-образ бота и пушит в GHCR
   (`ghcr.io/botkin-health/botkin-bot`).
2. **Deploy**: по SSH на сервере в каталоге `/opt/botkin` выполняет
   ```bash
   # idempotent upsert резолвнутого тега в .env (источник истины для compose)
   docker compose -f docker-compose.prod.yml pull
   docker compose -f docker-compose.prod.yml up -d --wait
   ```
   То есть тянет готовый образ из GHCR и пересоздаёт контейнеры. **На сервере ничего не собирается.**

Файл `.github/workflows/deploy-prod.yml` — единственный источник истины по шагам.

### Тег прод-образа хранится в `/opt/botkin/.env` (`IMAGE_TAG`)

`docker-compose.prod.yml` резолвит образ как `ghcr.io/botkin-health/botkin-bot:${IMAGE_TAG:-latest}`,
а `IMAGE_TAG` читается из `/opt/botkin/.env`. Поэтому **перед `up -d`** workflow идемпотентно
вписывает резолвнутый тег в `.env` (upsert: `sed` по существующей строке либо `>>` append).
Это работает и на выкате нового sha, и на **откате** (`-f image_tag=…`) — откат тоже
перезаписывает `IMAGE_TAG` в `.env`, поэтому остаётся стабильным.

Это критично: без записи в `.env` любой последующий `docker compose up` **без** переменной
окружения `IMAGE_TAG` (ручной, auto-heal, рестарт docker-демона, чужой деплой) резолвил бы
`${IMAGE_TAG:-latest}` из `.env`, где строки не было, и прод молча откатывался на
закэшированный/прежний образ. Прецедент: 16.06.2026 фикс #125 (`:1edeccd`) задеплоился, но через
несколько минут прод сам откатился на `:7699b30` — именно из-за отсутствия `IMAGE_TAG` в `.env`.

## Откат

Повторно запустить «Deploy prod» с параметром `image_tag=<готовый тег образа>` —
тогда стадия сборки пропускается и деплоится уже существующий образ:
```bash
gh workflow run deploy-prod.yml -f image_tag=<sha-готового-образа>
```

## Конфигурация на сервере

- Каталог стека: `/opt/botkin`
- Файл `.env` **лежит на сервере** (оператор кладёт `/opt/botkin/.env` один раз) и
  **не входит в репозиторий**. Workflow синкает на сервер только `docker-compose.prod.yml`.
- Если на сервере нет `.env` — деплой упадёт с явной ошибкой.

> ⚠️ Перед первым деплоем убедись, что в `/opt/botkin/.env` заданы
> `TELEGRAM_WEBHOOK_SECRET` и `WHOOP_STATE_SECRET` — без них webhook останется
> без аутентификации, а WHOOP-привязка упадёт.

## Диагностика

```bash
# Логи бота (последние 50 строк)
ssh root@116.203.213.137 "docker logs healthvault_bot --tail 50"

# Следить в реальном времени
ssh root@116.203.213.137 "docker logs -f healthvault_bot"

# Поиск ошибок
ssh root@116.203.213.137 "docker logs healthvault_bot 2>&1 | grep ERROR"

# Статус контейнеров
ssh root@116.203.213.137 "docker ps | grep healthvault"
```

### Частые проблемы

| Проблема | Причина | Решение |
|---|---|---|
| Деплой упал на проверке `.env` | На сервере нет `/opt/botkin/.env` | Положить `.env` на сервер |
| Контейнер постоянно перезапускается | Ошибка импорта/синтаксиса в коде | Проверить `docker logs healthvault_bot` |
| Ошибка подключения к БД | Контейнер PostgreSQL не готов | Проверить `docker compose ps`, при необходимости перезапустить |
| Прод сам откатился на старый образ после успешного деплоя | В `/opt/botkin/.env` нет строки `IMAGE_TAG` → `docker compose up` без env резолвит `${IMAGE_TAG:-latest}` на закэшированный образ | Уже исправлено: workflow персистит `IMAGE_TAG` в `.env` перед `up -d`. Проверить, что строка есть: `grep '^IMAGE_TAG=' /opt/botkin/.env` |

## Лучшие практики

1. Прогнать тесты и линтер локально перед мержем в `main`.
2. Проверить логи сразу после деплоя.
3. При проблеме — откатиться на предыдущий `image_tag` (см. «Откат»), не чинить на проде.
