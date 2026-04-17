# Research: MCP-серверы для wearables (Pace, Fitness MCP, garmin_mcp, Open Wearables)

Дата: 2026-04-17 · По запросу: «Pace MCP и Fitness MCP — брать готовый или строить свой?»

## TL;DR

- 🏆 **Победитель: `Taxuspt/garmin_mcp`** — open source, Python, 96 инструментов, тот же `python-garminconnect` что уже используется в HealthVault, ставится за 30 минут в Claude Desktop. Это не замена текущему стеку — это новый интерфейс поверх него.
- ❌ **Pace и Fitness MCP (getfast.ai)** — закрытые SaaS, данные идут через их облако и Terra API. Применять не стоит: у тебя уже есть прямой доступ к Garmin API, отдавать данные третьим сторонам смысла нет.
- 💡 **Open Wearables** — open source, Docker, поддерживает Garmin + Apple Health + Whoop + Oura + Samsung. Интереснее как долгосрочная замена Python-пайплайну, но требует больше усилий на внедрение.
- 🎯 **Эффект от garmin_mcp:** вместо «написать скрипт → запустить → прочитать JSON → интерпретировать» можно спросить Claude прямо: *«как у меня менялся HRV последние 4 недели и что с этим делать»* — и получить ответ с данными.

---

## Контекст

У тебя уже есть Garmin API через `scripts/garmin/download_garmin_data.py` (использует `python-garminconnect`), данные хранятся в `data/garmin/`. Текущий интерфейс — либо запуск скриптов, либо SQL-запросы к PostgreSQL. MCP-сервер добавляет третий интерфейс: **живой разговор с Claude**, который сам дёргает Garmin в реальном времени. Это особенно полезно для семейного трекинга — спросить «что у мамы с пульсом за последний месяц» без написания скриптов под каждый вопрос.

---

## Лучший open source (ранжированный список)

### 1. [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp) — ⭐380

**Язык:** Python 99.7%  **Активность:** активная разработка (80 коммитов, 23 открытых PR)

**Что делает:** MCP-сервер с 96 инструментами для Garmin Connect. Использует `python-garminconnect` (тот же что в HealthVault). Работает через OAuth-токены сохранённые локально.

**96 инструментов разбиты по категориям:**
| Категория | Кол-во | Примеры |
|---|---|---|
| Health & Wellness | 31 | HRV, stress, Body Battery, sleep, resting HR |
| Activity Management | 14 | историческая активность, последние тренировки |
| Training & Performance | 9 | VO₂max (расчётный!), training load, fitness age |
| Workouts | 8 | создание и управление тренировками |
| Nutrition | 8 | нутриент-логи из Garmin |
| Weight Tracking | 5 | история веса |
| Women's Health | 3 | релевантно для жены |
| Devices | 7 | статус устройств |

**Применимость к HealthVault:**
- Установить в Claude Desktop → спрашивать «как изменился мой HRV за последние 4 недели» без SQL
- Доступ к `Training & Performance` → расчётный VO₂max прямо через Claude (пока не сделал тест в TriSystems)
- `Women's Health` инструменты — для жены если подключить её аккаунт отдельно
- Можно использовать внутри HealthVault как Python-вызов — MCP-сервер запускается локально

**Чего не хватает:**
- Не агрегирует данные нескольких Garmin-аккаунтов (семейный трекинг — только один логин)
- Нет cross-device корреляций (Garmin × Zepp × питание) — это остаётся за твоим Python-стеком
- Нет истории в PostgreSQL — каждый запрос идёт в Garmin API напрямую (rate limits!)

---

### 2. [Open Wearables](https://openwearables.io/) — ⭐1100+

**Язык:** TypeScript/Python  **Активность:** активная (v0.3 вышел январь 2026, v0.3.3 beta март 2026)

**Что делает:** Полноценная self-hosted платформа: инgest данных → нормализация → health scoring → MCP-сервер для любого LLM (Claude, GPT, Gemini). Поддерживает Garmin, Apple Health, Whoop, Oura, Polar, Suunto, Samsung Health, Google Health Connect, Ultrahuman. Разворачивается через Docker Compose.

**Что даёт сверх garmin_mcp:**
- **Multi-device агрегация** — один MCP для всего (Garmin + Apple Health жены + Oura если купишь)
- **Нормализованные health scores** — HRV index, sleep score, recovery score — алгоритмы открытые, аудируемые
- **Аномалии и тренды** — сервер сам флагует отклонения, не только отдаёт сырые данные
- **Open algorithms** — можно адаптировать scoring под свои нормы

**Применимость к HealthVault:**
Потенциальная замена части Python ingestion-скриптов. Но требует полноценного деплоя (Docker Compose), миграции данных из существующего PostgreSQL, и настройки под 5 членов семьи с разными аккаунтами.

**Чего не хватает:**
- Zepp/Xiaomi: в планах, ещё не поддерживается (критично для тебя — весы)
- Сложнее в setup, чем garmin_mcp
- Не проверял насколько хорошо работает с Garmin конкретно (vs Apple Health)

---

## Закрытые/SaaS — пропускаем

| Сервис | Почему не нужен |
|---|---|
| **Pace** (неизвестный автор, getfast.ai?) | SaaS через Terra API, данные уходят в чужое облако, бесплатно пока, но может стать платным |
| **Fitness MCP** (getfast.ai) | То же самое — их Claude Connector, закрытый SaaS |
| **Fulcra Personal MCP** | Коммерческий, $200+ данных из 200+ источников, избыточно |
| **Pierre / AI Endurance** | Триатлон-специфика, узкая аудитория |

**Принцип:** у тебя уже есть прямой Garmin API → отдавать данные третьим сторонам нет смысла ни технически, ни с точки зрения приватности семейных данных (мама, сыновья).

---

## Нашёл бонусом: garmin_mcp + HealthVault = синергия

Интересный паттерн использования который нашёл в Slowtwitch forum: люди запускают MCP-сервер не только в Claude Desktop, но и **вызывают его инструменты программно внутри своего Python-кода**. Это значит:

```python
# Концепт: вместо скрипта download_garmin_data.py
# можно дёргать MCP-инструменты напрямую как Python-функции
from garmin_mcp import get_hrv_data, get_sleep_score

# Или: LLM-агент (aiogram бот) вызывает MCP-инструменты
# когда пользователь спрашивает «как я спал»
```

Таким образом garmin_mcp может стать унифицированным слоем доступа к Garmin и в Claude Desktop, и в Telegram-боте.

---

## Рекомендация

**Прямо сейчас:** установить `garmin_mcp` в Claude Desktop — 30 минут работы.

```json
// ~/.config/claude/claude_desktop_config.json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["garmin-mcp"],
      "env": {
        "GARMIN_USERNAME": "твой@email.com",
        "GARMIN_PASSWORD": "пароль"
      }
    }
  }
}
```

После этого в Claude Desktop можно задавать вопросы напрямую к Garmin данным без промежуточных скриптов.

**Через 1-2 месяца:** оценить Open Wearables как более полный multi-device MCP. Особенно актуально когда появится CGM (Dexcom/Libre) — Open Wearables уже готовится его поддерживать.

**Не делать:** не трогать Pace/Fitness MCP SaaS — избыточно и потеря контроля над данными.

---

## Следующие шаги для HealthVault

- [ ] Установить `garmin_mcp` в Claude Desktop: `pip install garmin-mcp` или через uvx
- [ ] Пройти OAuth-авторизацию: `garmin-mcp-auth` (обрабатывает MFA)
- [ ] Проверить расчётный VO₂max через `get_training_performance` инструмент — до теста в TriSystems
- [ ] Посмотреть Women's Health инструменты на предмет применимости для жены (41)
- [ ] Добавить garmin_mcp в список источников в `docs/LONGEVITY_BENCHMARKS.md` — третий референс после Blueprint и Singularity Club
- [ ] Создать задачу в `todo.md`: оценить Open Wearables как multi-device агрегатор когда купишь CGM

---

*Sources:*
- [Show HN: Pace MCP](https://news.ycombinator.com/item?id=47658617)
- [Open Wearables](https://openwearables.io/)
- [Open Wearables intro post](https://www.themomentum.ai/blog/introducing-open-wearables-the-open-source-api-for-wearable-health-intelligence)
- [garmin_mcp GitHub](https://github.com/Taxuspt/garmin_mcp)
- [ChatForest: Fitness MCP Servers review](https://chatforest.com/reviews/fitness-wearables-mcp-servers/)
- [Garmin chat connector overview](https://gadgetsandwearables.com/2026/03/16/garmin-chat-connector/)
