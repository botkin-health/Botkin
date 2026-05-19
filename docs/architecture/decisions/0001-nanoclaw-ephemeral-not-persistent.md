# 0001. NanoClaw: ephemeral spawn-containers per session, не persistent per user

**Status:** Accepted (11.05.2026, повторно подтверждено 19.05.2026 после повторной ошибки)
**Date:** 2026-05-11 → 2026-05-19
**Deciders:** Александр + Claude
**Context:** проектируем agent-слой для cohort users (Sprint 1a/1b)

## Решение

Для AI-агентов на сервере Botkin используем **NanoClaw-style host-orchestrator** (host-процесс, который spawn'ит ephemeral контейнеры per session с Claude Agent SDK внутри). НЕ persistent containers per user 24/7.

NanoClaw как продукт: https://github.com/qwibitai/nanoclaw — open-source Node.js, MIT, ~3,900 строк. Стек: host (Node) + spawn (Bun + Claude Agent SDK), coordination через SQLite inbound/outbound DB.

## Альтернативы (отвергнуты)

| Подход | Что | Почему отвергнут |
|---|---|---|
| **Persistent container per user** (docker-compose service per user, 24/7) | nc-sasha, nc-andrey, nc-nika как always-on сервисы | Дорого по памяти (один container = ~300 MB), не масштабируется на 50+ юзеров. Нет встроенной памяти между sessions (нужно строить отдельно). Не использует Claude Agent SDK в правильном flow. |
| **Свой Python FastAPI агент** (`botkin-agent:v0.1`) | Простой Python-микросервис: FastAPI + Anthropic SDK + tools через HTTP. Persistent per user. | То же что выше — повторяет отвергнутую модель. **19.05.2026 фактически построен и откатан** — это и был наш learning loop. См. § ниже. |
| **Никакого агента, только legacy aiogram** | Бот парсит команды, нет LLM-диалога | Не достигает цели «agent думает с тобой про здоровье». Это backup для дедлайнов, не цель. |

## Последствия

### Позитивные
- ✅ Память per agent group хранится host'ом — централизованно, легко backup-ить
- ✅ Spawn-контейнеры эфемерные → не платим за idle memory
- ✅ Claude Agent SDK используется в задумке (не raw API)
- ✅ Multi-platform поддержка (Telegram + WhatsApp + Slack + Discord) — для Vision семейного mesh-а
- ✅ Credential vault через OneCLI proxy — секреты не в контейнерах
- ✅ Можно гибридить с приватным слоем (личный Claude на компе пользователя через MCP) — это и есть Vision

### Негативные / trade-offs
- ⚠️ Стек гетерогенный: Botkin = Python + NanoClaw = Node. Нужен Node.js 20+ на хосте
- ⚠️ Меньше control vs свой код — мы зависим от качества и развития NanoClaw
- ⚠️ Не интегрирован с нашим Sprint 1a (JWT, agent_tools_api) — нужно мостить
- ⚠️ Кривая обучения (Claude Agent SDK + NanoClaw concepts: agent group, sessions, channels)

### Anti-patterns (что НЕ делать)
- ❌ **НЕ строить свой Python-агент в docker-сервисе per user** — это уже отвергли дважды
- ❌ **НЕ persistent containers per user** — основная отвергнутая модель
- ❌ **НЕ HTTP `/agent/process` POST как entry point** — NanoClaw использует SQLite inbound/outbound вместо HTTP
- ❌ **НЕ помещать API ключи в контейнеры** — должны быть в vault

## История (как мы дошли до этого решения)

### 04.05.2026 — Sprint 1a spec
[`~/FamilyHealth/_botkin_planning_private/2026-05-04-cohort-agents-design.md`](file://~/FamilyHealth/_botkin_planning_private/2026-05-04-cohort-agents-design.md) описал «NanoClaw containers» как persistent per user. Sprint 1a инфраструктура построена под эту модель: БД-колонки `container_id`/`container_port`, JWT auth, telegram_router форвардит на `http://<container>:<port>/agent/process`.

### 11.05.2026 — глубокое погружение в реальный NanoClaw
Изучили [github.com/qwibitai/nanoclaw](https://github.com/qwibitai/nanoclaw). Обнаружили принципиальную разницу: реальный NanoClaw использует ephemeral spawn-контейнеры per session, SQLite-coordination, host-orchestrator. Sprint 1b plan (persistent containers) помечен **OBSOLETE**. Решили: Андрей онбордится через legacy в 14.05; возврат к агентам — после cleanup и multi-user hardening.

### 19.05.2026 — повтор ошибки и откат
В свежей сессии Claude (я) не дочитал OBSOLETE-пометку на Sprint 1b plan, построил `botkin-agent:v0.1` — Python FastAPI persistent container per user. Это **точный отвергнутый подход**. Прошли весь цикл: образ собран, контейнер запущен, JWT-handshake работает, **бот для Alex'а перестал отвечать** (попутно нашёл и починил отдельный баг с порт-маппингом).

Откатили: контейнер/image удалены, БД-поля очищены, ALEX_JWT_SECRET убран. Этот ADR создан, чтобы в третий раз не повторить.

## Sprint 1a инфраструктура — статус

Что построено в Sprint 1a (04.05) и **остаётся актуальным для будущей правильной интеграции с NanoClaw**:
- `users.container_id`, `users.container_port`, `users.jwt_secret` — пригодны
- RLS-политики по cohort — пригодны
- `webhook/jwt_auth.py` — пригоден
- `webhook/agent_tools_api.py` (8 endpoints) — пригоден как «tools» для агентов NanoClaw
- `webhook/telegram_router.py` — нужна доработка: вместо forward на персональный контейнер юзера должен форвардить на NanoClaw host-process

## Что дальше (для будущей правильной реализации Sprint 1b)

1. Запустить NanoClaw host-process на Hetzner отдельным сервисом (Node.js контейнер)
2. Добавить Telegram-канал через `/add-telegram` skill NanoClaw
3. NanoClaw host получает Telegram update → spawn ephemeral container с pack:cardiac / pack:bariatric / pack:female-cycle (по `pack_name` в users)
4. Контейнер вызывает наши tools на `bot:8081/api/agent/*` через JWT
5. Memory per agent group монтируется bind-mount из `/opt/botkin-agent-memory/{user_id}/`
6. Credential vault — пока через env (упрощённо), потом OneCLI

**Время:** 2-3 дня. **НЕ для FFF Tbilisi** — после конференции, после spike по NanoClaw locally.

## Ссылки

- Реальный NanoClaw repo: https://github.com/qwibitai/nanoclaw
- Spec Sprint 1a (приватная — содержит имена и use-cases): `~/FamilyHealth/_botkin_planning_private/2026-05-04-cohort-agents-design.md`
- Sprint 1b plan (OBSOLETE, не исполнять): `~/FamilyHealth/_botkin_planning_private/2026-05-06-cohort-agents-sprint-1b.md`
- Ветка с откатанной попыткой 19.05: `feat/nanoclaw-agent-v0.1` (не мержена в main)
- PR #12 — фикс webhook + rollback NanoClaw v0.1: https://github.com/Lyskovsky/Botkin/pull/12
