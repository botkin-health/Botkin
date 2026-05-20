# SPEC: NanoClaw Agent Bot (@BotkinAgent_bot)

**Дата:** 2026-05-19
**Автор:** Alex + Claude
**Статус:** Approved — pending implementation

## Контекст

19.05 утром попытка построить `botkin-agent:v0.1` (Python FastAPI persistent container per user) была откачена как повторение отвергнутого подхода — см. ADR-0001. Правильная архитектура — NanoClaw (host-process + ephemeral spawn-containers per session).

Сегодня обсудили развилку: миграция `@Botkin_md_bot` в NanoClaw (B) vs параллельный `@BotkinAgent_bot` (A). Выбран A — обоснование ниже.

## Почему вариант A, а не B

**B — миграция `@Botkin_md_bot` целиком — высокорискованна за 9 дней до FFF:**
- Telegram Mini App (`/day`, `/share`, settings) подписаны `bot_token` через `initData` → ломается при смене бота
- Food/voice/photo парсеры (`core/food_parser.py` + AssemblyAI) — месяцы отладки edge cases, рерайт в TS skills = новые баги
- Latency: каждое сообщение = полная Claude-инференция (~10-15 сек, ~$3-5/день при 4 active юзерах)
- Reversibility: откатывать миграцию за день до демо сложно

**A — параллельный бот — даёт 80% UX за 20% риска:**
- Разговорная сверхсила (память + multi-turn + tool composition) появляется и в A, и в B
- Папа/мама онбордятся в `@BotkinAgent_bot` как в **единственный** бот (для них нет когнитивного оверхеда «два бота»)
- Long-term путь: после FFF постепенно мигрируем handler-за-handler из старого бота → в NEXT-секции ROADMAP

## Архитектура

```
┌─ Hetzner ─────────────────────────────────────────────────────────┐
│                                                                   │
│  @Botkin_md_bot (webhook)  ←──── без изменений                   │
│   ├─ aiogram                                                      │
│   ├─ food/voice/photo logging                                     │
│   ├─ Mini App webhook (8081)                                      │
│   └─ /sync /day /share                                            │
│                                                                   │
│  @BotkinAgent_bot (long polling) ←─── NEW                        │
│   └─ NanoClaw host process (Node.js)                              │
│        ├─ /add-telegram skill (channels branch)                   │
│        ├─ central.db (entity model: user → group → session)       │
│        ├─ per-session inbound.db / outbound.db                    │
│        ├─ ephemeral spawn-container per session                   │
│        │    ├─ Claude Agent SDK                                   │
│        │    ├─ per-agent CLAUDE.md (стиль: Alex/папа/мама)        │
│        │    ├─ memory (skill outputs, notes)                      │
│        │    └─ tools → HTTP → bot:8081/api/agent/* (JWT)          │
│        └─ memory bind-mount /opt/botkin-agent-memory/{user}/      │
│                                                                   │
│  webhook/agent_tools_api.py (8081) ←──── tools API (reused)      │
│   └─ 8 endpoints из Sprint 1a (с JWT-auth, RLS per-cohort)        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

## План реализации (фазами)

### Phase 1: Local spike (Mac) — сегодня

1. `git clone https://github.com/nanocoai/nanoclaw.git ~/nanoclaw-spike`
2. `bash nanoclaw.sh` — ставит Node 20+, pnpm 10+, Docker если нет
3. `/init-first-agent` (через Claude Code) — создаёт первый agent group
4. `TELEGRAM_BOT_TOKEN=...` в `.env` (наш токен из 1Password)
5. `/add-telegram` skill — копирует адаптер с channels branch, билд
6. `/manage-channels` — связать `@BotkinAgent_bot` с agent group «alex»
7. **Acceptance:** написать боту «привет» → получить осмысленный ответ от Claude без tools

### Phase 2: Tools bridge

8. Проверить какие читающие эндпоинты есть в `webhook/agent_tools_api.py`. Если каких-то нет — добавить:
   - `get_recent_bp(days)` — последние замеры АД
   - `get_sleep_summary(days)` — суммарный сон
   - `get_food_summary(date)` — что съел в этот день
   - `get_health_context()` — KB summary + диагнозы + последние анализы
9. JWT — для тестовой первой агентской сессии генерим **один** долгоживущий токен с claim `cohort=owner, user_id=895655`, кладём в spawn-container ENV
10. Написать NanoClaw tool/skill, который зовёт `http://host.docker.internal:8081/api/agent/*` с этим JWT
11. **Acceptance:** «как мои данные за неделю?» → агент сам зовёт tools → внятный ответ

### Phase 3: Per-agent CLAUDE.md

12. Написать CLAUDE.md под Alex (тон, контекст диагнозов из FamilyHealth, доступные tools, цели)
13. Bind-mount этого файла в spawn-container
14. **Acceptance:** агент знает контекст «кому отвечает» без напоминаний в каждом сообщении

### Phase 4: Production deploy на Hetzner

15. На сервере: Node 20+ (через nvm или apt), pnpm 10+
16. Clone репо в `/opt/nanoclaw/`
17. `.env` с production-токеном
18. Запуск как systemd service (NanoClaw host process)
19. Бинд-маунт `/opt/botkin-agent-memory/{user_id}/` для persistence
20. Файрвол: NanoClaw host не выставляется наружу, общается с tools API через docker network / 127.0.0.1
21. **Acceptance:** написал боту с телефона из любой страны → отвечает с актуальными данными

### Phase 5: Семья (после FFF, если будет время)

22. Создать agent groups: «papa», «mama» с своими CLAUDE.md (тон, упор на BP / медикаменты)
23. `/manage-channels` — связать tg chat_id папы с group «papa»
24. JWT-токены для них с `cohort=family, user_id=<их id>`

## Риски и митигации

| Риск | Митигация |
|---|---|
| NanoClaw production deploy untested на нашем стеке | Phase 1 = локальный spike, Phase 4 только после Phase 1-3 локально |
| Полный конфликт по портам / docker.sock на Hetzner | Изолированная docker network для NanoClaw, отдельный compose-файл |
| Memory growth (spawn-контейнеры утекают) | Мониторинг + auto-cleanup. NanoClaw v2 это должен делать сам через session lifecycle |
| Telegram polling vs webhook на @Botkin_md_bot — конфликт | НЕТ — это два разных bot_token, никакого пересечения |
| Стоимость Claude inference на каждое сообщение | Мониторим, ставим лимиты на длину истории |

## Что НЕ в scope

- ❌ Миграция handlers из `@Botkin_md_bot` (это NEXT)
- ❌ Write-tools агента (логирование еды/BP голосом через агента) — Phase 2 только чтение
- ❌ Multi-platform (Discord, Slack) — это Vision-level, не сейчас
- ❌ OneCLI credential vault — пока ENV-переменные в spawn-container, secrets vault — потом
- ❌ Subagents и сложные skills (Karpathy-wiki и т.п.) — после стабилизации основы
