# Отчёт за время твоего отъезда (20.05.2026)

> Пока тебя не было — закрыл Phase 1.5 → 3, потестил Phase 4, всё закоммитил.
> **Бот работает**, можешь продолжать тестить @BotkinAgent_bot.

## Что сделано

### ✅ Phase 1.5 — Auto-chown systemd timer
- Каждые 30 сек делает `chown -R 1000:1000` сессионных папок NanoClaw
- Решает grandle с readonly-db при перезапуске
- Юнит-файлы: `/etc/systemd/system/nanoclaw-chown.{service,timer}`

### ✅ Phase 2 — Tools bridge через MCP
- Написан MCP server в `/opt/nanoclaw/groups/alex/skills/botkin/server.ts` (bun)
- 7 tools: `get_user_profile`, `get_dashboard_summary`, `get_recent_meals`, `get_kb_value`, `log_meal_text`, `log_bp`, `log_supplement`
- JWT 1-летний для агента (user_id=895655, container_id=`nanoclaw-alex`)
- `users.container_id='nanoclaw-alex'` выставлен в Postgres
- Botcker compose: добавлен второй port bind `172.17.0.1:8081:8081` чтобы spawn-контейнеры достали `bot:8081/api/agent/*` через `host.docker.internal`
- `NO_PROXY=host.docker.internal` в env MCP-сервера (иначе OneCLI proxy ломал локальные вызовы)

**End-to-end протестировано** реальными вопросами через MCP:
| # | Вопрос | Ответ агента |
|---|---|---|
| 1 | «покажи кратко главные цифры» | сервер не отвечал (фикс HTTP_PROXY) |
| 2 | «покажи мой вес и шаги за неделю» | Вес 76.6 кг, шаги 7648/день avg — реальные данные ✅ |
| 3 | «какие были последние анализы крови?» | «не нашёл в Botkin» — анализы лежат в FamilyHealth/, не в БД ⚠️ |
| 4 | «какой у меня семейный кардиориск?» | сначала «нет данных» (CLAUDE.local.md не подхватился) |
| 5 | «доза 5000 МЕ?» | угадал D3 общими знаниями, не из контекста |
| 6 | «доза витамина D» (после фикса) | «D3 5000 МЕ ежедневно. Витамин D 35.6 нг/мл» ✅ |
| 7 | «семейные риски по линии отца» | подробно про ПСА папы, FCH, метаболику, БЦА ✅ |

### ✅ Phase 3 — Health context в CLAUDE.local.md
- Полный профиль: текущие цифры, семейный анамнез (FCH по отцу, дислипидемия мамы), lifestyle (баня, голодание, алкоголь), цели 2026 (PhenoAge, вес, FFF)
- **Обнаружена грабля**: Claude Agent SDK в headless mode НЕ читает `CLAUDE.local.md`. Лечится через `container_configs.mcp_servers.botkin.instructions` — этот JSON-field попадает в composed CLAUDE.md как фрагмент.
- Сейчас работает: агент знает про мою D3, кардиориск отца, и т.п.

### ✅ Документация (закоммичена в `feat/nanoclaw-agent-phase-1-3`)
- `docs/projects/2026-05_nanoclaw-agent-bot/STATUS.md` — финальное состояние + 16 граблей с решениями
- `docs/projects/2026-05_nanoclaw-agent-bot/SPEC.md` — обоснование архитектуры
- `docs/projects/2026-05_nanoclaw-agent-bot/PLAN.md` — Phase 4-6 + tech debt
- `docs/projects/2026-05_nanoclaw-agent-bot/QUESTIONS_FOR_ALEX.md` — открытые вопросы
- `docs/ROADMAP.md` — обновлён, NanoClaw из «отложено» переехал в done-history
- `docker-compose.prod.yml` — dual port bind 8081

### ✅ Git
- Ветка: **`feat/nanoclaw-agent-phase-1-3`** запушена на GitHub
- PR не создал — 1Password залочен (твой отпечаток нужен). Создашь сам:
  - https://github.com/Lyskovsky/Botkin/pull/new/feat/nanoclaw-agent-phase-1-3
  - Описание готово к копированию из коммит-сообщения

## ⚠️ Что осталось / на что обратить внимание

### Открытые вопросы (см. `QUESTIONS_FOR_ALEX.md`)
Самые важные:
1. **Один бот @BotkinAgent_bot для всех или отдельные?** — нужно знать для онбординга папы/мамы
2. **Хочешь ли ротировать Anthropic-ключ?** (он был в чате)
3. **Голосовые/фото в @BotkinAgent_bot** — что с ними делаем
4. **Что показывать на FFF** — конкретный demo-сценарий

### Что не сделал из-за отсутствия 1Password
- JWT не сохранил в 1Password (op требует отпечаток). Положил карточкой кодовой строкой в чате — добавишь когда вернёшься. Карточка должна быть:
  - Title: «Botkin agent JWT — Alex»
  - credential: см. `/opt/nanoclaw/groups/alex/container.json` mcpServers.botkin.env.BOTKIN_JWT (на сервере)
- PR не создал (как указано выше)

### Tech debt из Phase 3
- **CLAUDE.local.md vs mcp_servers.botkin.instructions дублирование** — сейчас содержимое скопировано вручную. Если будешь править — нужно править ОБА места. PLAN.md описывает фикс: автосинк через cron/systemd path watcher.
- Длительный JWT (1 год) в plain ENV — будем класть в OneCLI vault как secret (тоже в PLAN.md)

## Готовность к Phase 4

| Acceptance | Status |
|---|---|
| Агент отвечает на сообщения | ✅ |
| Помнит контекст между сессиями | ✅ |
| Видит реальные данные из Postgres | ✅ |
| Знает контекст здоровья Alex | ✅ |
| Знает семейный анамнез | ✅ |
| Может логировать (BP, supplement, meal) | ⏳ не протестировано (Alex должен инициировать) |
| Анализы крови из KB | ❌ нужно либо загрузить в Postgres, либо новый tool под FamilyHealth |
| Voice/photo | ❌ не в scope MVP (используй @Botkin_md_bot) |

## Как продолжить тестировать

Просто пиши `@BotkinAgent_bot` любые вопросы про здоровье. Я слежу за логами по запросу. Полезные команды для тебя на сервере:

```bash
ssh root@116.203.213.137
journalctl -u nanoclaw-v2-3282970f -n 50 -f       # реал-тайм логи
tail -f /opt/nanoclaw/logs/nanoclaw.log
docker ps --filter "name=nanoclaw"                  # spawn-контейнеры
sqlite3 /opt/nanoclaw/data/v2.db                    # central DB
```

Если что-то ломается — открой `STATUS.md § Lessons learned` (16 пунктов), скорее всего там уже есть твоя ошибка.
