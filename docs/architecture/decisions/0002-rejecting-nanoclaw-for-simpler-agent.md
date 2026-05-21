# ADR-0002: Отказ от NanoClaw в пользу более простой схемы AI-агента

**Дата:** 2026-05-21
**Статус:** Accepted
**Автор:** Александр Лысковский
**Связи:** [ADR-0001](0001-nanoclaw-ephemeral-not-persistent.md), [project 2026-05_nanoclaw-agent-bot](../../projects/2026-05_nanoclaw-agent-bot/)

## Контекст

19–20.05.2026 на Hetzner был задеплоен NanoClaw (v2.0.64) как host-process + ephemeral spawn-containers per session для параллельного бота `@BotkinAgent_bot`. Phase 1–3 работали: Claude Agent SDK через OneCLI proxy, MCP-server `botkin` с 7 tools (через `webhook/agent_tools_api.py`), rich health-context CLAUDE.local.md, JWT-auth и RLS-изоляция по cohort.

Но за два дня вылез ряд проблем (см. STATUS.md проекта, секция «Lessons learned» — 16 пунктов):
- Сложность стека: NanoClaw host + OneCLI vault + OneCLI postgres + spawn-контейнеры + systemd-таймер для chown + dual port bind в docker-compose.prod.yml.
- ~3.8 GB на диске (NanoClaw image 3 GB + OneCLI 710 MB + /opt/nanoclaw 179 MB) на 38 GB сервере, который и так был на 95% полным.
- Хрупкость: readonly-db после restart, OneCLI HTTPS_PROXY ломает MCP-вызовы на host.docker.internal, CLAUDE.local.md не подхватывается Claude SDK в headless режиме (приходится класть в `container_configs.mcp_servers.botkin.instructions` — недокументированный workaround).
- Два бота для пользователя: `@Botkin_md_bot` (food/voice/Mini App) и `@BotkinAgent_bot` (разговор с агентом) — когнитивный оверхед, особенно для папы/мамы которым изначально планировался один бот.

При этом главная ценность — multi-turn разговор с памятью и tool composition — воспроизводится прямым вызовом Anthropic SDK из основного aiogram-бота, использующего те же `webhook/agent_tools_api.py` как tools API.

## Решение

**Сворачиваем NanoClaw.** AI-врач реализуется как handler внутри существующего `@Botkin_md_bot`:
- Прямой вызов Anthropic Messages API (или Agent SDK без NanoClaw-обёртки) из aiogram-процесса
- История диалога — в Postgres (новая таблица или поле в `users`)
- Tools — переиспользуем существующий `webhook/agent_tools_api.py` (тот же контракт что был у MCP-сервера NanoClaw)
- Health context — берём из `users.agent_system_prompt` + `pack_name` (уже наполнено для Alex)

Название подхода — **BotkinClaw** (игра слов NanoClaw → BotkinClaw, бот сам играет роль «контейнера» в JWT-контракте; упрощённая инфра вместо NanoClaw).

### Что остаётся ценным активом

- `webhook/agent_tools_api.py` — JWT+RLS, 8 endpoints. Переиспользуется. Может быть позже доступен и личному Claude пользователя через MCP — это всё ещё в vision (см. [CLAUDE.md](../../../CLAUDE.md) «Гибридная приватность»).
- `users.jwt_secret`, `users.agent_system_prompt`, `users.pack_name`, `users.kb_status` — поля для агентов остаются.
- ADR-0001 (ephemeral, не persistent) — остаётся валидным архитектурным принципом *если* в будущем вернёмся к контейнеризованным агентам. Сейчас агент не в контейнере вообще — он handler в aiogram-процессе.

### Что снесено с Hetzner (21.05.2026)

- `/opt/nanoclaw/` целиком
- Docker image `nanoclaw-agent-v2-3282970f` (3.05 GB), container
- OneCLI: `/root/.onecli/`, image `ghcr.io/onecli/onecli` (710 MB), `onecli-postgres-1` container
- systemd units: `nanoclaw-v2-3282970f.service`, `nanoclaw-chown.service`, `nanoclaw-chown.timer`
- БД: `users.container_id='nanoclaw-alex'` → `NULL`
- Bot Postgres `agent_system_prompt` для Alex упоминает NanoClaw + @BotkinAgent_bot — обновится при первой настройке BotkinClaw

Бэкап на сервере: `/root/nanoclaw-backup-2026-05-21.tar.gz` (66 MB) — `/opt/nanoclaw` + systemd unit-файлы + `/root/.onecli/`. Можно удалить через месяц если не понадобится.

Освобождено: 3.8 GB. Диск был 95% → 77%.

### Судьба `@BotkinAgent_bot`

Открытый вопрос. Варианты:
1. Переиспользовать как «второй бот» для BotkinClaw-агента (тогда два бота снова, обратно к минусу).
2. Revoke в BotFather, AI-врач живёт внутри `@Botkin_md_bot` как ещё один handler.
3. Оставить токен в 1Password «про запас» (без активной интеграции).

Рекомендация — **(2)** для папы/мамы (один бот), но финальное решение — за Alex когда будет начат BotkinClaw.

## Почему не «нужно было сделать сразу BotkinClaw, не тратить 2 дня на NanoClaw»

Спайк NanoClaw был не зря:
1. Подтвердил что архитектура tools API (JWT+RLS+8 endpoints) переживёт смену рантайма агента — это переиспользуемый актив.
2. Дал почувствовать сложность ephemeral-контейнерной схемы. ADR-0001 убедил нас не делать persistent — но и эфемерные оказались дороги. Теперь оба варианта проверены опытом.
3. Прокачали `agent_system_prompt` rich-context для Alex — это переезжает в BotkinClaw как есть.

## Что дальше

- TODO: SPEC для BotkinClaw (handler-структура, история в БД, конфликты с уже-running aiogram-handlers, rate-limit Claude API)
- TODO: решить судьбу `@BotkinAgent_bot`
- TODO: обновить `users.agent_system_prompt` (убрать упоминания «NanoClaw» / «@BotkinAgent_bot»)
