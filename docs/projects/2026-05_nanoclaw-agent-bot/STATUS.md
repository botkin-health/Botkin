# NanoClaw Agent Bot (параллельный @BotkinAgent_bot)

**Status:** 🔴 REJECTED (2026-05-21)
**Started:** 2026-05-19
**Closed:** 2026-05-21 — выбран более простой подход (см. ADR-0002)
**Owner:** Александр Лысковский
**Cohort:** owner first → family (папа, мама) → early_user

## ⛔ Проект свёрнут (2026-05-21)

После двух дней работы с NanoClaw (Phase 1–3 задеплоены 20.05) решено отказаться от этой инфры и сделать AI-врача более простым способом — прямой вызов Claude API из существующего `@Botkin_md_bot` (aiogram-handler + те же `webhook/agent_tools_api.py` как tools). Подробности и обоснование — в [ADR-0002](../../architecture/decisions/0002-rejecting-nanoclaw-for-simpler-agent.md).

**Что снесено с Hetzner 21.05.2026:**
- `/opt/nanoclaw/` (179 MB) + docker image `nanoclaw-agent-v2-*` (3.05 GB) + container
- OneCLI: `/root/.onecli/` + image `ghcr.io/onecli/onecli` (710 MB) + onecli-postgres
- systemd: `nanoclaw-v2-3282970f.service`, `nanoclaw-chown.service`, `nanoclaw-chown.timer`
- БД: `users.container_id` обнулён для пользователя `nanoclaw-alex`
- Бэкап на сервере: `/root/nanoclaw-backup-2026-05-21.tar.gz` (66 MB) — на случай если понадобится вернуться

**Что осталось как актив (переиспользуется новым подходом):**
- `webhook/agent_tools_api.py` — 8 endpoints с JWT+RLS
- `users.jwt_secret` — для подписи JWT
- В БД: `users.agent_system_prompt` (rich health context), `users.pack_name`
- Telegram-бот `@BotkinAgent_bot` (id 8327780367) — токен в 1Password, можно либо переиспользовать как «sandbox для нового агента», либо revoke. Решение TBD.

**Файлы STATUS.md / SPEC.md / PLAN.md ниже сохранены как исторические** — не следовать им.

---

## (Историческая часть, до сворачивания)

## Цель

Поднять параллельного Telegram-бота `@BotkinAgent_bot` на NanoClaw — для разговорного UX с памятью и доступом к данным через tools. Существующий `@Botkin_md_bot` (aiogram) остаётся без изменений: food logging / Mini App / /sync / /share продолжают работать. См. SPEC.md для обоснования варианта A vs B.

## Текущее состояние

- ✅ Бот создан в BotFather: `@BotkinAgent_bot` (id 8327780367), токен в 1Password (карточка `wq4v5xg36b2rg33qejhyf3zudu`, поле `BotkinAgent_bot`)
- ✅ **Phase 1 deploy на Hetzner (20.05.2026)** — NanoClaw v2.0.64 в `/opt/nanoclaw/`, systemd `nanoclaw-v2-3282970f.service`, OneCLI vault, Telegram adapter, agent group "Alex" с CLAUDE.local.md
- ✅ **Phase 1 acceptance** — бот отвечает осмысленно, помнит контекст беседы (Claude SDK session persistence работает)
- ✅ **Phase 1.5** — `nanoclaw-chown.timer` systemd-юнит каждые 30 сек chown'ит сессионные папки в uid 1000 (фикс readonly-db после restart)
- ✅ **Phase 2 (20.05.2026)** — MCP-server `botkin` подключён, агент успешно вызывает tools API и возвращает реальные данные из Postgres
- ✅ **Phase 3 (20.05.2026)** — Полный CLAUDE.local.md с контекстом здоровья: семейный анамнез (отец/мать), текущие цифры, lifestyle, фокус-цели на 2026
- ⏳ Phase 4 — Per-agent для папы / мамы (после FFF)
- ⚠️ Tech debt: см. секцию ниже

## Архитектура (финальная Phase 1-3)

```
Telegram @BotkinAgent_bot (long polling)
    │
    ▼
NanoClaw host (Node.js, systemd nanoclaw-v2-3282970f.service)
  /opt/nanoclaw/
    ├ data/v2.db (central DB)
    ├ data/v2-sessions/ag-1779238102546-alex01/sess-*/
    │   ├ inbound.db (host writes, container reads)
    │   └ outbound.db (container writes, host reads)
    └ groups/alex/
        ├ CLAUDE.local.md (rich health context)
        └ skills/botkin/server.ts (MCP server)
    │
    ▼ docker run (per session, ephemeral)
NanoClaw agent container (uid 1000, image nanoclaw-agent-v2-*)
  ├ Claude Agent SDK (через OneCLI proxy → api.anthropic.com)
  └ MCP server "botkin" (bun subprocess)
      │
      ▼ HTTP NO_PROXY=host.docker.internal
http://host.docker.internal:8081/api/agent/* (= 172.17.0.1:8081)
  + Authorization: Bearer <JWT>
    │
    ▼
healthvault_bot (FastAPI, прод-bot @Botkin_md_bot)
  └ webhook/agent_tools_api.py (8 endpoints, JWT auth, RLS по cohort)
    │
    ▼
healthvault_postgres (данные здоровья Alex)
```

## Ключевые конфиги

| Файл | Что в нём |
|---|---|
| `/opt/nanoclaw/.env` | `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, **`ONECLI_URL=http://172.17.0.1:10254`** |
| `~/.onecli/config.json` | `{"api-host": "http://172.17.0.1:10254"}` |
| `~/.onecli/.env` | `ONECLI_BIND_HOST=172.17.0.1` |
| `/opt/nanoclaw/groups/alex/CLAUDE.local.md` | Health context для Alex |
| `/opt/nanoclaw/groups/alex/skills/botkin/server.ts` | MCP server (7 tools) |
| `/opt/healthvault/docker-compose.prod.yml` | dual port bind 8081 (127.0.0.1 + 172.17.0.1) |
| `/etc/systemd/system/nanoclaw-chown.timer` | каждые 30 сек chown сессий |
| `users.container_id = 'nanoclaw-alex'` в Postgres | stable JWT container_id |
| JWT для агента | TTL 1 год, signed by `users.jwt_secret`. Хранится в env конфига MCP-клиента. |

## Lessons learned (Phase 1)

### Грабли и решения

1. **`nanoclaw.sh` пытается качать Debian пакеты внутри Docker build** — если VPN на хосте перехватывает DNS, build падает. Решение: ставить с хоста где нет VPN (Hetzner — да, Mac с включённым VPN — нет).

2. **OneCLI bind по умолчанию на `127.0.0.1`** — недоступен для spawn-контейнеров (они идут через `host.docker.internal` → `172.17.0.1`). Решение: `ONECLI_BIND_HOST=172.17.0.1` в `~/.onecli/.env` (создать руками), плюс `~/.onecli/config.json` тоже с `http://172.17.0.1:10254`.

3. **`ncl groups create` создаёт DB-запись с UUID-идентификатором, не `ag-<ts>-<rand>`** — OneCLI требует identifier `[a-z][a-z0-9-]*`, UUID начинающийся с цифры fail. Решение: либо использовать setup-скрипт `bash setup/add-channel-and-agent.sh`, либо ручкой делать INSERT с правильным форматом.

4. **`ncl groups create` НЕ создаёт `container_configs` row** — host-sweep падает с "Container config not found". Решение: ручной `INSERT INTO container_configs (agent_group_id, skills, ...) VALUES (..., '"all"', ...)`.

5. **`ncl groups create` НЕ создаёт OneCLI agent identity** — нужен POST на `http://127.0.0.1:10254/api/agents` с `{"name": ..., "identifier": <agent_group_id>}`.

6. **`ncl groups create` НЕ создаёт `groups/<folder>/CLAUDE.local.md`** — без этого агент стартует но без CLAUDE-инструкций. Решение: руками `mkdir groups/alex && create CLAUDE.local.md`.

7. **NanoClaw как root → spawn-контейнер бежит как `node` (uid 1000)** — потому что в `container-runner.js` `--user` НЕ передаётся когда `hostUid in (0, 1000)`. Сессионные файлы (`outbound.db`) создаются root'ом, а node user не может писать → `attempt to write a readonly database`. Решение временное: `chown -R 1000:1000 data/v2-sessions/ groups/`. Длинное решение: либо запустить NanoClaw под uid 1000 (нужен docker group access), либо inotify-хук, либо запатчить NanoClaw на post-create chown.

8. **`/add-telegram` skill требует `channels` branch** — после `git clone --depth 1` нет remote-tracking branch. Решение: `git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*" && git fetch origin`.

9. **Setup абортится если OneCLI postgres падает из-за full disk** — мы упёрлись в 100% диска после первого build (chromium-сборка ~9 GB). Решение: `docker builder prune -af` после установки. Длинное решение: vacuum политика для unused images.

10. **`NANOCLAW_SKIP=channel`** в setup приводит к тому что после установки бот не привязан к agent group — нужно либо запустить `pnpm run nanoclaw -- channel` отдельно, либо ручкой делать `ncl messaging-groups update` + `ncl wirings create` + chown.

11. **`ONECLI_URL` в `/opt/nanoclaw/.env`** прописан как `127.0.0.1:10254` при setup. После того как OneCLI bind переехал на 172.17.0.1 — нужно обновить и здесь. Иначе host-sweep падает с `OneCLIError: fetch failed`.

12. **OneCLI HTTPS_PROXY перехватывает все HTTP-вызовы из контейнера**, включая локальные на `host.docker.internal:8081`. Решение: добавить `NO_PROXY=host.docker.internal,localhost,127.0.0.1` (и lowercase `no_proxy`) в env MCP-сервера. Без этого MCP-server получает `Empty reply from server` потому что OneCLI proxy не знает что делать с не-HTTPS целью.

13. **Spawn-контейнер не имеет доступа к `bot:8081`** по умолчанию (бот публикует порт только на 127.0.0.1, контейнер на default bridge). Решение: добавить `172.17.0.1:8081:8081` к ports в `docker-compose.prod.yml` healthvault — теперь контейнеры могут стучаться через `host.docker.internal:8081`.

14. **JWT для агента TTL 1 час по умолчанию** (`AGENT_JWT_TTL_HOURS`). Это неудобно для постоянного агента — нужно генерить долгоживущий вручную через `jwt.encode({user_id, container_id, exp: +365д, iat}, user.jwt_secret)`. У Alex сейчас exp = 2027-05-20.

15. **OneCLI agent identifier должен совпадать с `agent_group_id`** (формат `ag-<ts>-<rand>`), не с user-friendly name. NanoClaw в spawnContainer использует `agentGroup.id` как identifier для `ensureAgent`. Если в OneCLI есть Default Agent с identifier="default" и наш Alex с identifier="ag-...", OneCLI gateway правильно роутит по agent token.

16. **🚨 `CLAUDE.local.md` НЕ подхватывается Claude Agent SDK в headless mode** — это самое неочевидное. NanoClaw header композит-файла даже говорит "Edit CLAUDE.local.md for per-group content", но composedClaudeMd НЕ делает `@./CLAUDE.local.md` import. И Claude SDK в headless режиме CLAUDE.local.md не загружает (только interactive Claude Code это делает).
    **Симптом:** написал rich health context в `groups/alex/CLAUDE.local.md`, но агент отвечает «у меня нет данных» на любой вопрос из контекста (семейный анамнез, текущие препараты, и т.п.).
    **Решение:** положить весь health context в `container_configs.mcp_servers.botkin.instructions` (JSON-field). `composeGroupClaudeMd` создаст `mcp-botkin.md` fragment в `.claude-fragments/` и автоматически добавит `@./.claude-fragments/mcp-botkin.md` в композит CLAUDE.md. **Проверено end-to-end:** агент теперь знает что Alex принимает D3 5000 МЕ, кратко перечисляет ПСА-риск отца, FCH-наследование и т.п.
    **Стоит ли обращать в upstream issue:** Да — либо документировать что CLAUDE.local.md только interactive, либо добавить `@./CLAUDE.local.md` в composed CLAUDE.md.

### Что бы сделал иначе

- Не делать `NANOCLAW_SKIP=channel` — пусть setup сам прогонит add-telegram интерактивно. Я думал что обойду TUI через env-vars, но channel-step требует interactive выбора который проще пройти один раз вручную через ssh+tmux.
- Сразу после `bash nanoclaw.sh` делать `chown -R 1000:1000 data/ groups/` чтобы избежать readonly-db.
- ONECLI_BIND_HOST=172.17.0.1 поставить ДО запуска setup (в `/opt/nanoclaw/.env`).

## Принципы (зачем именно так)

1. **Изоляция от прода** — webhook `@Botkin_md_bot` не трогаем; long-polling `@BotkinAgent_bot` отдельным процессом
2. **Mini App не страдает** — initData всё ещё подписан старым bot_token
3. **Папа/мама** онбордятся **только** в `@BotkinAgent_bot` (для них один бот, разговорный UX сразу)
4. **Долгосрочно** — постепенная миграция handler-за-handler в NEXT-секции ROADMAP. Сейчас НЕ переписываем food/voice/photo

## Связи

- ADR: `../../architecture/decisions/0001-nanoclaw-ephemeral-not-persistent.md`
- SPEC: `SPEC.md` (план реализации + почему вариант A)
- Bot: `@BotkinAgent_bot` (id 8327780367)
- NanoClaw upstream: https://github.com/nanocoai/nanoclaw (v2.0.63, 29k stars на 19.05.2026)
