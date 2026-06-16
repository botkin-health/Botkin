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

## Права на bind-mount данных и ночной sync

Контейнер `healthvault_bot` работает под непривилегированным пользователем
`botkin` (**uid 10001**, см. `USER botkin` в `Dockerfile.bot`). Данные смонтированы
bind-mount'ом: host `/opt/botkin/data` → контейнерный `/app/data` (плюс `/app/logs`).

**Проблема прав.** Часть писателей в `/opt/botkin/data` — это Mac-пайплайн
(`scripts/push_garmin_to_db.py`, `scripts/garmin/download_garmin_data.py` и др.),
который заливает файлы по `root@`-SSH. Созданные им файлы получают владельца **root
(uid 0)** с правами `644` → для `botkin` (uid 10001) это категория «others», только
чтение. Любой server-side `/sync` (контейнерный `botkin`) на перезаписи такого файла
падает с `PermissionError: [Errno 13] Permission denied`. Прецедент 15–16.06.2026:
ночные синки молча падали, `/sync` в боте вернул пачку ❌ (weather, netatmo, garmin,
pg_sync).

**Почему host-side `chown` НЕ работает.** `chown -R 10001:10001 /opt/botkin/data` с
хоста возвращает `0`, но владельца **не меняет** (uid-маппинг overlayfs / containerd-
снапшоттера). Менять права нужно **изнутри контейнера от root**:

```bash
docker exec -u 0 healthvault_bot chown -R 10001:10001 /app/data /app/logs
```

**Постоянное решение (выбрано 16.06.2026): chown pre-step в cron.** Ночной sync на
сервере запускается host-cron'ом; перед `sync_all.sh` добавлен idempotent chown-шаг,
который переводит всё дерево обратно на `10001:10001` непосредственно перед каждым
прогоном (каждые 30 мин в окне 04–20):

```cron
*/30 4-20 * * * docker exec -u 0 healthvault_bot chown -R 10001:10001 /app/data /app/logs >> /var/log/botkin_sync.log 2>&1 ; docker exec healthvault_bot bash /app/scripts/server/sync_all.sh >> /var/log/botkin_sync.log 2>&1
```

- Разделитель `;` (не `&&`): даже если chown икнул, sync всё равно пробуем.
- Cron живёт на **хосте**, вне репозитория → источник истины по правам — этот файл.
- Это закрывает старый пункт ROADMAP «Auto-chown … (фикс readonly-db после restart)»:
  отдельный systemd-таймер не нужен, chown делается прямо перед потреблением данных.

> Альтернативы, которые **не** выбрали: (2) entrypoint-self-heal в образе (USER root →
> chown → drop в botkin) — чинит только при рестарте/redeploy, не ловит root-файлы,
> записанные Mac-пайплайном между рестартами; (3) chown в самих Mac-писателях —
> устраняет первопричину, но требует правок во всех писателях. Если когда-нибудь
> Mac-пайплайн перестанет писать через `root@`-SSH — cron-шаг можно будет убрать.

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
| `/sync` / ночной sync падает с `PermissionError: [Errno 13]` на `/app/data/...` | Mac-пайплайн записал файлы как root (uid 0), контейнерный `botkin` (uid 10001) не может перезаписать | Разовый фикс: `docker exec -u 0 healthvault_bot chown -R 10001:10001 /app/data /app/logs`. Постоянный — cron pre-step (см. «Права на bind-mount данных и ночной sync»). Проверить chown-шаг в crontab: `crontab -l \| grep chown` |

## Лучшие практики

1. Прогнать тесты и линтер локально перед мержем в `main`.
2. Проверить логи сразу после деплоя.
3. При проблеме — откатиться на предыдущий `image_tag` (см. «Откат»), не чинить на проде.
