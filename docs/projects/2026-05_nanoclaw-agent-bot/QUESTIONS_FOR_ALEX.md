# Вопросы для Alex к возвращению

> 20.05.2026 — после Phase 1-3 deploy, накопилось решений которые я не могу принять без тебя.

## 🔴 Решения нужны сразу (блокируют Phase 4)

### 1. Один бот или несколько для семьи?

Сейчас @BotkinAgent_bot привязан к Alex. Когда папа/мама/Ника начнут пользоваться — два варианта:

- **A. Один бот @BotkinAgent_bot для всех.** NanoClaw создаст отдельные messaging_groups per Telegram chat_id и автоматически роутит в их agent group. Один токен в BotFather, общая инфра.
- **B. Боты на юзера**: @PapaBotkin_bot, @MamaBotkin_bot и т.д. Каждый со своим токеном.

**Рекомендую A** — проще, дешевле, NanoClaw для этого и сделан. Но хочешь по приватности «папин агент = свой бот» — давай B.

### 2. Ключ Anthropic — оставляем тот же или делаем ротацию?

Ты сказал «не переживаю, не меняем». Но он лежит сейчас в:
- `/opt/nanoclaw/.env` на сервере
- `/opt/nanoclaw/groups/alex/container.json` (внутри mcpServers env как `BOTKIN_JWT` — нет, это JWT, не Anthropic key)
- На самом деле Anthropic key в `~/.onecli` vault (OneCLI хранит)
- В 1Password у тебя (карточка «Claude API Key — Botkin NanoClaw»)
- **И** в твоей переписке со мной (потенциальная утечка)

Если решил ротировать — рост на 2 минуты:
1. Console.anthropic.com → revoke
2. Create new → копирую в OneCLI и в `/opt/nanoclaw/.env`
3. Перезапускаю NanoClaw

### 3. JWT для агента — где хранить долгосрочно?

Сейчас JWT (1 год) в `groups/alex/container.json` plain text в env MCP-сервера. Альтернатива — положить в OneCLI vault как secret, MCP-server читает оттуда. Делать?

## 🟡 Полезно решить когда есть время

### 4. Tools для агента — что ещё нужно?

Прямо сейчас агент видит:
- профиль / 7-дневная сводка / последние meals / KB по ключу

Прошу проверить сценарии в твоём use case. Какие данные ты ХОЧЕШЬ чтобы агент видел, но он сейчас не видит? Например:
- HRV / RHR тренды
- Конкретные анализы (последний холестерин, ферритин)
- Список текущих добавок
- Тренировочные сессии
- Сон детально (стадии, awakenings)
- Семейные риски (текст про папу/маму)

### 5. Voice-сообщения и фото — как роутить?

@BotkinAgent_bot сейчас НЕ умеет в voice/photo (NanoClaw Telegram-adapter принимает text). Если ты пришлёшь голосовое — оно либо упадёт, либо агент скажет «не понял».

Варианты:
- A. Игнорируем voice/photo для агента, оставляем `@Botkin_md_bot` для них
- B. Сделать MCP tool «transcribe_voice» и patch NanoClaw Telegram adapter принимать voice
- C. Перенаправление: «отправь голосовое в @Botkin_md_bot, текстовую часть продублируй сюда»

### 6. Демо-сценарий для FFF

Подумай что показать на сцене 28-31.05:
- Просто чат с @BotkinAgent_bot? — слабо, без вау
- @BotkinAgent_bot + screenshare дашборда + lab анализов?
- Дуэт ботов: photo в @Botkin_md_bot, спрашиваем у агента?
- Кейс: «я ел такое — что у меня с холестерином после еды?» (но мы не делаем CGM)

### 7. Когда онбордим папу/маму

Готовы или после конференции? Папа в СПб — нужно его согласие на хранение данных. Условие onbording в SPEC прописано.

## 🟢 Чисто инфо / не блокирующее

### 8. Old @Botkin_md_bot healthcheck unhealthy

Видно в `docker ps` как `(unhealthy)`. Бот работает, но Docker healthcheck падает (`pgrep` не в образе). Spawned task уже создан, разберём отдельно.

### 9. Sprint 1a инфра — что осталось

`webhook/agent_tools_api.py` использовался в Phase 2 — все 8 endpoints полезны. `jwt_auth.py`, `telegram_router.py` — пока не задействованы напрямую (NanoClaw сам роутит), но в коде лежат. Решить позже: оставить как опциональный legacy-path или удалить.

### 10. Mac spike (nanoclaw-spike)

В `~/nanoclaw-spike` остался полу-сломанный install (упал на DNS из-за VPN). Можно удалить — `rm -rf ~/nanoclaw-spike`. Образы Docker тоже можно почистить `docker image rm nanoclaw-agent-v2-eff39ca7:latest`.
