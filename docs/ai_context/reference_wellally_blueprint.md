# WellAlly — Architecture Blueprint

> Версия: март 2026  
> Платформа: macOS M5, Python 3.11, SQLite, Telegram Bot, Anthropic Claude API

---

## 1. Общая схема системы

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                               │
│                                                                     │
│  Oura Ring API    Apple Health    Lab PDFs (OCR)    Manual input    │
│       │                │               │                 │         │
└───────┼────────────────┼───────────────┼─────────────────┼─────────┘
        │                │               │                 │
        ▼                ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        STORAGE LAYER                                │
│                                                                     │
│   health.db (SQLite, iCloud Drive)     profile_context.json        │
│   ├── daily_metrics                    ├── medical_history          │
│   ├── lab_results                      ├── problem_list (P001–P006) │
│   ├── agent_reports                    ├── current_location         │
│   ├── tasks                            └── observations             │
│   ├── checkins + context_events                                     │
│   ├── problem_list                                                  │
│   ├── periods                                                       │
│   ├── memory                                                        │
│   └── experiments                                                   │
└─────────────────────────────────────────────────────────────────────┘
        │                                           │
        ▼                                           ▼
┌───────────────────────┐               ┌───────────────────────────┐
│   LIFESTYLE AGENTS    │               │     MDT SPECIALISTS (9)   │
│   (ежедневно 08:00)   │               │     (воскресенье 23:00)   │
│                       │               │                           │
│  SleepAgent  (today)  │               │  Oncologist  + PubMed    │
│  MovementAgent (yday) │               │  Gastro      + PubMed    │
│  StressAgent   (yday) │               │  Cardio      + PubMed    │
│  EnergyAgent   (yday) │               │  Hematology  + PubMed    │
└──────────┬────────────┘               │  Nephrology  + PubMed    │
           │                            │  Nutrition   + PubMed    │
           │                            │  Endocrine   + PubMed    │
           │                            │  Psychiatry  + PubMed    │
           │                            │  Pulmonology + PubMed    │
           │                            └──────────┬────────────────┘
           │                                       │
           └──────────────┬────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      GP AGENT (Claude Sonnet)                       │
│                                                                     │
│  Daily 08:00    → утренний брифинг (4–7 предложений)               │
│  Weekly Mon 07:00 → интервальная история + problem list             │
│  Monthly 1st    → стратегический обзор 30/90 дней                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
         Telegram Bot    Task Agent     Reports (md)
                         │
               ┌─────────┴──────────┐
               ▼                    ▼
           SQLite tasks       macOS Reminders
               ▲                    │
               └────────────────────┘
                  reminders_sync.py
                  (polling 3ч)
```

---

## 2. Расписание

| Время | День | Что происходит |
|-------|------|----------------|
| 08:00 | ежедневно | `refresh_data()` → lifestyle agents → GP daily → Telegram |
| 21:00 | ежедневно | Evening checkin — открывающий вопрос в Telegram |
| 23:00 | воскресенье | 9 MDT специалистов → `agent_reports` → follow-up незакрытых задач |
| 07:00 | понедельник | GP weekly report → Telegram → task extraction → Reminders |
| 09:30 | 1-е число | GP monthly strategic report → Telegram |
| каждые 3ч | — | `reminders_sync.py` → completed Reminders → SQLite |

---

## 3. Агентная архитектура

### 3.1 Lifestyle Agents (ежедневный слой)

```
Данные за СЕГОДНЯ:
  SleepAgent ──────────────────────┐
    sleep.totalSleep, deep, REM    │
    sleep_score, contributors      │
    sleepStart/End                 │
                                   ▼
Данные за ВЧЕРА:               GP Daily
  MovementAgent ─────────────► (Claude Sonnet)
    steps, distance_km             │
    active_kcal, activity_score    ▼
                               4–7 предложений
  StressAgent ────────────────► утреннего брифинга
    hrv.avg, resting_heart_rate
    mindful_min, daylight_min
    checkin stress_notes

  EnergyAgent ───────────────►
    readiness_score, SpO2
```

**Правило молчания**: агент не выдаёт бриф если нет данных.  
**Правило нуля**: `0` в поле ≠ реальный ноль, = датчик не записал.

### 3.2 MDT Specialists (еженедельный слой)

Каждый специалист работает независимо по стандартам своей дисциплины:

```
Специалист получает:
  ├── lifestyle stats (7/30/90 дней)
  ├── lab_results (с окнами валидности)
  ├── problem_list (P001–P006)
  ├── medical_history из profile_context.json
  └── данные свежести (DATA_FRESHNESS_WINDOWS)

Специалист выдаёт:
  ├── клиническое суждение по своему домену
  ├── флаги и наблюдения
  └── ссылки PubMed (через NCBI E-utilities API)

Сохраняется в agent_reports:
  └── {agent_type, agent_name, date, findings, pubmed_ids}
```

### 3.3 GP Agent (синтезирующий слой)

```
GP DAILY читает:
  ├── lifestyle briefs (те агенты, у кого есть данные)
  ├── missing agents list (явный gap)
  └── evening checkin из context_events

GP WEEKLY читает:
  ├── MDT reports из agent_reports (последние 14 дней)
  ├── lifestyle flags за 7 дней (агрегированные паттерны)
  ├── lab freshness check
  └── problem_list статус

GP MONTHLY читает:
  └── stats 30/90 дней + полный контекст

Методология GP:
  ├── Problem List (Weed, 1968) — P001–P006
  ├── Interval History — дельта с прошлого визита
  ├── Safety Net (RCGP) — триггеры для немедленного обращения
  ├── Watchful Waiting — явные критерии перехода в действие
  └── Dual Process — быстрые паттерны + медленный анализ
```

---

## 4. Data Freshness Windows

Основаны на клинических протоколах ESMO / NCCN:

| Тест | Окно (дни) | Приоритет | Обоснование |
|------|-----------|-----------|-------------|
| CEA, CA19.9 | 90 | critical | Онкомаркеры в ремиссии — раз в 3 мес (ESMO) |
| HGB, WBC, PLT, MCV | 90 | high | CBC при Xeloda монотерапии |
| LDH, Creatinine, ALT, AST | 90 | medium | Метаболический мониторинг |
| Albumin | 120 | medium | Нутритивный статус |
| B12, Folate | 180 | high | Макроцитоз — explicit missing_note |
| Ferritin, Cholesterol | 180 | medium | Нутритивные/метаболические |

Если данные устарели — агент пишет `"данные от [дата], актуальность под вопросом"` и не делает уверенных выводов.

---

## 5. Task Lifecycle

```
GP Report (weekly/monthly/on-demand)
         │
         ▼
  task_agent.extract_tasks()
  (Claude Haiku — JSON array)
         │
         ├──► SQLite tasks table
         │    {type, priority, content, deadline, status}
         │
         └──► macOS Reminders "Health" list
              {title с emoji, body с [task_id:N], due date}
                    │
         ┌──────────┼──────────────┐
         │          │              │
    /done <id>  /dismiss <id>  Reminders.app ✓
    Telegram    Telegram            │
         │          │              │
         ▼          ▼              ▼
    resolve_task()            reminders_sync.py
    + complete_                (каждые 3ч)
    macos_reminder()          find [task_id:N]
                              → resolve_task()

Sunday follow-up:
  get_overdue_tasks(days_old=7) → Telegram reminder
```

---

## 6. Evening Checkin Flow

```
21:00 scheduled:
  generate_opening_question()
    ├── читает Oura данные дня
    ├── читает calendar события (если есть)
    └── читает последний checkin
  → один тёплый контекстуальный вопрос → Telegram

Пользователь отвечает (handle_text перехватывает):
  continue_checkin() — до 3 turns
    └── [CHECKIN_COMPLETE] → finalize_checkin()

finalize_checkin():
  ├── Claude Haiku извлекает JSON:
  │   {day_score, energy_level, mood, physical_symptoms,
  │    notable_events, stress_notes, wins, food_notes,
  │    sleep_comment, free_text}
  ├── save_checkin() → checkins table (raw Q&A)
  └── save_context_event() → context_events
      (day_score, evening_summary — для GP)
```

---

## 7. База данных (SQLite)

```sql
daily_metrics      -- Oura + Apple Health (1 строка/день)
lab_results        -- анализы с датой, значением, источником
agent_reports      -- выводы всех агентов (MDT + GP + lifestyle)
tasks              -- задачи с lifecycle (open/completed/dismissed)
checkins           -- raw вечерние чекины (question + answer)
context_events     -- структурированные события (day_score, summary...)
problem_list       -- P001–P006 с статусом и триггерами
periods            -- медицинские и travel периоды
memory             -- факты из разговоров (арбитр)
experiments        -- активные n=1 эксперименты
conversation_history -- история чата
```

---

## 8. Файловая структура

```
~/health_scripts/
├── telegram_bot.py          # точка входа, scheduling, команды
├── health_db.py             # вся работа с SQLite
├── health_ai.py             # Claude chat + morning report (legacy)
├── gp_agent.py              # GP: daily / weekly / monthly
├── lifestyle_agents.py      # Sleep / Movement / Stress / Energy
├── checkin_agent.py         # вечерний чекин
├── task_agent.py            # задачи + macOS Reminders
├── wellally_consult.py      # 9 MDT специалистов
├── pubmed_client.py         # NCBI E-utilities API
├── reminders_sync.py        # Reminders → SQLite polling
├── import_oura.py           # Oura API → SQLite
├── import_apple_health.py   # Apple Health → SQLite
└── watch_and_import.sh      # file watcher для auto-import

~/Library/LaunchAgents/
├── com.larry.health.bot.plist          # бот (KeepAlive)
├── com.larry.health.daily.plist        # daily import 08:00
├── com.larry.health.watcher.plist      # file watcher
└── com.larry.health.reminders-sync.plist  # sync каждые 3ч

~/Library/Mobile Documents/.../health/data/
├── health.db                # основная база (iCloud sync)
├── profile_context.json     # медицинский профиль
└── reports/                 # сохранённые отчёты (md)
```

---

## 9. Внешние интеграции

| Сервис | Использование | Аутентификация |
|--------|---------------|----------------|
| Anthropic Claude API | все агенты (Haiku + Sonnet) | `~/.health_secrets/anthropic_key` |
| Oura API v2 | daily sleep + activity | `~/.health_secrets/oura_token` |
| Apple Health | шаги, ВСР, HRV export | XML import |
| NCBI PubMed E-utilities | доказательная база для MDT | без ключа (public) |
| Telegram Bot API | интерфейс пользователя | `~/.health_secrets/telegram_token` |
| macOS Reminders | задачи через AppleScript | системные права |
| iCloud Drive | sync базы и профиля | системная интеграция |

---

## 10. Модели по агентам

| Агент | Модель | Обоснование |
|-------|--------|-------------|
| GP (daily/weekly/monthly) | claude-sonnet-4-6 | Клиническое суждение, синтез |
| MDT специалисты (9) | claude-haiku-4-5 | Скорость, стоимость, параллельно |
| Checkin opener | claude-haiku-4-5 | Простая генерация вопроса |
| Checkin driver | claude-haiku-4-5 | Conversational turns |
| Checkin extractor | claude-haiku-4-5 | JSON extraction |
| Task extractor | claude-haiku-4-5 | JSON extraction из текста |
| Chat arbiter | claude-haiku-4-5 | Фоновое извлечение фактов |
