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
   docker compose -f docker-compose.prod.yml pull
   docker compose -f docker-compose.prod.yml up -d --wait
   ```
   То есть тянет готовый образ из GHCR и пересоздаёт контейнеры. **На сервере ничего не собирается.**

Файл `.github/workflows/deploy-prod.yml` — единственный источник истины по шагам.

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

## Лучшие практики

1. Прогнать тесты и линтер локально перед мержем в `main`.
2. Проверить логи сразу после деплоя.
3. При проблеме — откатиться на предыдущий `image_tag` (см. «Откат»), не чинить на проде.
