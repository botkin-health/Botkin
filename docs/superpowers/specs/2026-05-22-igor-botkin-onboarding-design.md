# Igor → Botkin: подключение полноценного семейного пользователя

**Дата:** 2026-05-22
**Автор:** Александр + Claude (Opus 4.7)
**Статус:** Design — ждёт user review

---

## 1. Контекст и цель

Игорь Лысковский (telegram_id `830908046`, 21 год, второй сын Александра) подключился к
`@Botkin_md_bot` 21.05.2026 и пока пользуется только функцией логирования еды (cohort
`external`, KB на сервере нет, `agent_system_prompt` пустой). На локальном маке
в `~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Игорь
Лысковский — Здоровье/` лежит расширенный архив здоровья: 76 файлов (PDF, JPEG, XLSX) за
2014–2026, плюс структурированный `knowledge_base.json` (52 KB) и `PROFILE.md`.

**Цель проекта:** дать Игорю работающего активного коуча (как у Павла Храпкина), который
видит всю его историю — анализы, аллерго-панели, мониторинг витамина D, тик-антитела,
прививки, диагнозы — и может отвечать на вопросы про здоровье, а не только про калории.

**Дополнительная цель — переиспользуемость:** через несколько недель Александр планирует
подключить таким же образом маму (Валерия Лысковская). Текущий проект должен оставить
после себя задокументированный, идемпотентный и проверяемый процесс onboarding'а нового
семейного юзера. После окончания этого проекта подключение мамы должно быть одной командой
скрипта плюс ревью сгенерированного промпта.

---

## 2. Scope

**В scope:**
- CLI-скрипт `scripts/onboard_family_user.py` с командами `--enroll`, `--refresh-kb`,
  `--refresh-prompt`, `--unenroll`, `--dry-run`, `--from-file`, `--force`, `--yes`.
- Шаблон промпта `scripts/server/agent_prompts/templates/family_active_coach.md` с
  placeholder'ами для подстановки персональных блоков.
- Декларативный реестр packs `core/packs.py` с типом `Pack` (`@dataclass(frozen=True)`)
  и записями `bariatric`, `cardiac`, `generic`, новый `respiratory_allergic`.
- Подключение Игоря: KB на сервер, cohort → `family`, pack → `respiratory_allergic`,
  персональный agent_system_prompt, welcome-сообщение со стилем обращения «ты».
- Полная документация: `docs/operations/onboard-family-user.md` (runbook), запись в
  `docs/ai_context/AI_CHANGELOG.md`, ADR при необходимости.
- Тесты: `tests/test_onboard_family_user.py` (валидация KB, шаблонизатор, dry-run
  идемпотентность, мок LLM-вызовов).
- Smoke-проверка после деплоя: Игорь действительно получает ответы от агента с учётом
  своих данных (E2E через `ask_agent(uid, query)`, не только HTTP-пинг — см. memory
  `feedback_e2e_means_ask_agent.md`).

**Не в scope (отдельные будущие проекты):**
- Self-serve upload PDF/JPEG юзером — это «проект C», отдельный brainstorm.
- LLM-парсинг новых PDF (`scripts/import/parse_lab_pdfs.py` уже есть, не трогаем).
- Watch-инфраструктура за изменениями FamilyHealth.
- Auto-detect когда KB устарел.
- Изменения в `telegram-bot/webhook/agent_tools_api.py` — он уже умеет читать
  `kb_<tid>.json` для любого cohort, ничего менять не надо.

---

## 3. Архитектура

```
┌─ Локальный мак ──────────────────────────────────────────────────┐
│  FamilyHealth/Игорь Лысковский — Здоровье/knowledge_base.json    │
│        │                                                          │
│        ↓                                                          │
│  scripts/onboard_family_user.py                                   │
│    ├─ читает KB из FamilyHealth                                  │
│    ├─ читает шаблон family_active_coach.md                       │
│    ├─ читает реестр packs (core/packs.py)                        │
│    ├─ Anthropic API → персонификация блоков промпта              │
│    │    (claude-sonnet-4-6 с fallback на 4-5 на 529/overload)    │
│    └─ scp + ssh psql (atomic)                                     │
└────────────────────┬─────────────────────────────────────────────┘
                     │ scp / ssh
┌────────────────────┴─────────────────────────────────────────────┐
│  Hetzner /opt/healthvault/                                       │
│    └─ kb_830908046.json                   ← новый файл           │
│                                                                   │
│  PostgreSQL users(telegram_id=830908046):                        │
│    ├─ cohort: external → family                                  │
│    ├─ pack_name: generic → respiratory_allergic                  │
│    └─ agent_system_prompt: '' → ~8 KB персонального промпта      │
└────────────────────┬─────────────────────────────────────────────┘
                     │ Telegram Bot API
              ┌──────┴──────┐
              │   Игорь    │  ← welcome-сообщение от @Botkin_md_bot
              └─────────────┘
```

### Ключевые архитектурные решения

1. **Только явный запуск скрипта** — никакого автоматического watch'а. Idempotent,
   безопасно прогнать второй раз. Пока юзеров ≤10, авто-sync создаёт больше рисков
   чем экономит времени.

2. **Шаблон — markdown с placeholder'ами**, не Python f-string. Ревьюится как
   документ, diff читаемый, генерация через `string.Template` (no eval surface).

3. **Персонификация через LLM-вызов.** Шаблон содержит каркас («ты агент Игоря,
   активный коуч»), а блоки `{focus_areas_block}`, `{chronic_block}`,
   `{open_questions_block}` генерятся Claude'ом из `knowledge_base.json` + `PROFILE.md`.
   Это переиспользуемая функция для будущего проекта C.

4. **Реестр packs — Python-модуль.** Pack — `@dataclass(frozen=True)`, потому что
   `dashboard_blocks` и `report_template` это код, не data. Никакого dynamic registry —
   packs известны на compile time.

5. **Persisted persona prompt — git-артефакт.** Финальный персональный промпт
   коммитится в `scripts/server/agent_prompts/<short_name>.md` (`igor.md`, потом
   `mom.md` и т. д.). Это даёт: (а) ревью через git diff, (б) восстановление если
   БД накроется, (в) возможность ручной правки + `--refresh-prompt --from-file`
   (повторная заливка без LLM-вызова).

6. **Privacy gate — в welcome-сообщении.** Не отдельный шаг согласия до заливки.
   Это сын, подключённый отцом через семейный канал — но в welcome чётко: где данные,
   кто имеет доступ, как отключиться. На «нет, удали» → `--unenroll`.

7. **Стиль обращения — параметр шаблона.** `--style ty` / `--style vy`. Default
   определяется по возрасту юзера в KB (>=50 → vy, иначе ty). Для Игоря — `ty`.

---

## 4. Компоненты

### 4.1 Новые файлы

#### `scripts/onboard_family_user.py`

CLI на argparse. Команды:

| Флаг | Действие |
|---|---|
| `--enroll --tid <id> --family-folder "<folder>" --pack <pack> --cohort <cohort>` | Полный onboarding |
| `--refresh-kb --tid <id>` | Только обновить KB на сервере (re-scp) |
| `--refresh-prompt --tid <id>` | Только пересоздать system_prompt (LLM-вызов) |
| `--refresh-prompt --tid <id> --from-file <path>` | Залить промпт из локального файла (без LLM) |
| `--unenroll --tid <id>` | Откат: удалить KB с сервера, очистить prompt, cohort → external |
| `--dry-run` | Показать что было бы сделано, ничего не менять |
| `--force` | Перезаписать существующий enrollment без вопросов |
| `--yes` | Не спрашивать confirmation gate |
| `--style {ty,vy}` | Стиль обращения, default по возрасту |
| `--send-welcome` | Отправить welcome-сообщение через Bot API |
| `--no-commit` | Не делать git commit персонального промпта |

#### `scripts/server/agent_prompts/templates/family_active_coach.md`

Markdown с placeholder'ами `{name}`, `{age}`, `{cohort_intro}`, `{pack_intro}`,
`{focus_areas_block}`, `{chronic_block}`, `{open_questions_block}`,
`{communication_style}`, `{relationship_to_owner}`. Каркас взят с `pavel.md`,
обобщён до шаблона. Каждый блок имеет fallback-инструкцию для LLM если данных
нет («если нет blood_tests — пиши "данных пока нет, при первом разговоре уточни"»).

#### `scripts/server/agent_prompts/igor.md`

Финальный персональный промпт Игоря — артефакт, коммитится в git. Параллель с
`pavel.md`, который уже лежит.

#### `core/packs.py`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Pack:
    name: str
    description: str
    focus_areas: tuple[str, ...]
    dashboard_blocks: tuple[str, ...]
    report_template: Optional[str]  # путь к Jinja2 шаблону отчёта, None если ещё нет

PACKS: dict[str, Pack] = {
    "bariatric": Pack(...),
    "cardiac": Pack(...),
    "generic": Pack(...),
    "respiratory_allergic": Pack(
        name="respiratory_allergic",
        description="Астма + аллерго-история + регулярный скрининг",
        focus_areas=("asthma_allergy_panel", "vitamin_d", "pollen_seasonal",
                     "tick_antibodies"),
        dashboard_blocks=("vitamin_d_trend", "allergy_history", "tick_antibodies"),
        report_template=None,  # пока без отчёта, добавится при необходимости
    ),
}

def get_pack(name: str) -> Pack:
    if name not in PACKS:
        raise ValueError(f"Unknown pack: {name!r}. Available: {list(PACKS)}")
    return PACKS[name]
```

#### `tests/test_onboard_family_user.py`

Pytest. Что покрывает:
- Парсинг `knowledge_base.json` (валидные/невалидные случаи)
- Шаблонизатор через `string.Template` (все placeholder'ы подставляются, fallback
  при отсутствии данных)
- Реестр packs: `get_pack("respiratory_allergic")` возвращает корректный объект,
  `get_pack("unknown")` падает с `ValueError`
- `--dry-run` идемпотентность (ничего не пишется в БД, scp не дёргается)
- Mock Anthropic LLM-вызова, проверка что промпт собирается
- Edge case: KB без `blood_tests` — шаблон не падает, fallback срабатывает

### 4.2 Документация

#### `docs/operations/onboard-family-user.md` (новый runbook)

Пошаговый гайд для будущих onboarding'ов (мама и далее). Содержит:
- Pre-flight чек-лист (есть ли KB, есть ли юзер в БД)
- Команды для `--dry-run` → `--enroll`
- Что проверить после (E2E через ask_agent)
- Как ручно поправить промпт и применить через `--from-file`
- Rollback через `--unenroll`
- Список packs с описаниями и ссылкой на `core/packs.py`
- Troubleshooting: что делать если LLM-вызов упал, что делать если scp прервался

#### `docs/ai_context/AI_CHANGELOG.md`

Запись `2026-05-22: Igor onboarded as family/respiratory_allergic, pack registry
introduced (core/packs.py), reusable onboarding script (scripts/onboard_family_user.py)`.

#### `docs/architecture/decisions/0003-pack-registry.md` (опциональный ADR)

Решение: packs хранятся в Python-модуле, не в БД, не в JSON. Альтернативы и почему
отвергнуты. Пишется если ревьюер сочтёт необходимым — в первой итерации можно пропустить.

### 4.3 Существующие файлы (трогаем минимально)

- **`docs/ai_context/AI_CHANGELOG.md`** — запись.
- **`deploy.sh`** (или его аналог) — убедиться что `scripts/server/agent_prompts/`
  синкается на сервер. Это **только для документации**: на самой работе промпт
  попадает на сервер через UPDATE в БД, не через файл.

### 4.4 Чего НЕ трогаем (важно)

- `telegram-bot/webhook/agent_tools_api.py` — `kb_value` уже умеет читать
  `kb_<tid>.json` для любого cohort (см. строка 325–340, fallback resolution).
- `core/agent_chat.py` — читает `agent_system_prompt` из БД, ничего менять не надо.
- Схема БД — все нужные поля уже есть (`cohort`, `pack_name`, `agent_system_prompt`).
- `scripts/import/parse_lab_pdfs.py` — KB у Игоря уже распарсен.
- Существующие промпты `pavel.md` и записи Павла/Андрея/Александра/Олега — не
  трогаем (см. защита от регрессии в § 6).

---

## 5. Data flow при `--enroll`

```
1. Pre-flight checks
   ├─ FamilyHealth/<folder>/knowledge_base.json существует
   ├─ users(telegram_id) есть в БД
   ├─ pack_name есть в PACKS registry
   ├─ Не enrolled? (kb на сервере + agent_system_prompt пустой)
   │   ├─ да → продолжаем
   │   └─ нет → требовать --force
   └─ Snapshot текущего состояния пользователя в БД
      → data/onboarding_snapshots/<tid>_<timestamp>.json

2. Валидация KB
   ├─ Загрузить JSON
   ├─ Поле "values" в биомаркерах (стандарт, memory: standard_kb_values_field)
   ├─ Sanity: хотя бы одно из blood_tests/ecg/diagnoses непустое
   ├─ Размер ≤ 1 MB
   └─ Падать с понятным сообщением если что-то не так

3. LLM-генерация персональных блоков
   ├─ Прочитать template family_active_coach.md
   ├─ Прочитать KB + PROFILE.md
   ├─ Anthropic call (claude-sonnet-4-6 с fallback на 4-5):
   │     system: "Сгенерируй focus_areas, chronic, open_questions блоки"
   │     user:   <шаблон> + <KB JSON> + <PROFILE>
   ├─ Распарсить ответ в три блока (JSON или markdown sections)
   ├─ Подставить через string.Template
   └─ Записать в scripts/server/agent_prompts/<short_name>.md

4. Confirmation gate (если не --yes)
   ├─ Показать: размер промпта, фрагмент (первые 500 симв), путь к промпт-файлу
   ├─ Показать: размер KB-файла, что попадёт на сервер
   ├─ Показать: какие колонки в БД обновятся (до/после)
   └─ y/n

5. Применение изменений
   ├─ scp /tmp/kb_830908046.json.tmp → /opt/healthvault/kb_830908046.json.tmp
   ├─ ssh: mv .tmp → kb_830908046.json (atomic)
   ├─ ssh: docker exec postgres test JSON валидный
   ├─ psql одна транзакция:
   │     UPDATE users SET
   │       cohort='family',
   │       pack_name='respiratory_allergic',
   │       agent_system_prompt='...'
   │     WHERE telegram_id=830908046;
   └─ При ошибке psql → ssh rm файла на сервере (rollback scp)

6. Post-flight verify
   ├─ ssh psql: SELECT cohort, pack_name, LENGTH(agent_system_prompt)
   │     WHERE telegram_id=830908046
   │     → ожидаем family/respiratory_allergic/~8000
   ├─ ssh ls -la /opt/healthvault/kb_830908046.json → exists, size matches
   ├─ E2E: POST /api/agent/ask с тестовым запросом
   │     "Какой у меня был последний витамин D и когда?"
   │     → ожидаем что в ответе есть число и дата из KB
   └─ Если что-то не так → ALERT, не писать "success"

7. Welcome (если --send-welcome)
   ├─ Текст (ты-форма): "Привет, Игорь! Папа подключил мне твою историю
   │     анализов. Теперь я знаю про твой витамин D, аллергии и прививки,
   │     и могу отвечать на вопросы. Данные приватные, лежат на сервере
   │     в Германии. Хочешь отключить — напиши папе. Попробуй: «какой
   │     у меня был последний витD?»"
   ├─ Bot API: sendMessage chat_id=830908046
   └─ Лог в agent_conversations (role=assistant, source=onboarding_welcome)

8. Git commit (локально)
   ├─ git add scripts/server/agent_prompts/igor.md
   ├─ git add core/packs.py (если впервые)
   ├─ git commit -m "agent: onboard Igor (telegram_id 830908046) ..."
   └─ Скрипт: "закоммитил локально, запушь когда готов"
```

### Rollback по шагам
- До шага 5 — ничего не было изменено
- После 5.scp до 5.psql — `ssh rm` файла
- После 5.psql — UPDATE с откатом значений из снапшота (шаг 1)

### `--unenroll`
Идёт по обратному порядку 5→1. UPDATE users SET cohort='external', pack_name='generic',
agent_system_prompt=''. ssh rm файла. Welcome-уведомление «доступ отключён, история
бесед сохранена». Snapshot тоже сохраняется (для возможного re-enroll).

---

## 6. Защита от регрессий (что не должно сломаться)

Поскольку проект меняет несколько потенциально критичных мест, нужно явно
зафиксировать что **не** должно сломаться:

1. **Существующие промпты Павла, Андрея, Александра, Олега.** Скрипт оперирует только
   указанным `--tid`. Проверка в тестах: запуск с `--tid 33831673` без `--force`
   падает (Павел уже enrolled).

2. **`kb_33831673.json` и `kb_836757955.json` на сервере.** scp пишет только файл
   с `--tid` юзера. Smoke-проверка: после деплоя `ls /opt/healthvault/kb_*.json`
   возвращает 3 файла (Pavel, Andrey, Igor), не 1.

3. **RLS-изоляция.** Игорь не должен видеть KB других. Проверка: запрос
   `/api/agent/kb_value?key=blood_tests.0` от Игоря возвращает его данные, от
   Александра возвращает данные Александра — каждый видит своё. JWT этого юзера
   привязан к его telegram_id, RLS-политика `agent_conversations_self` уже это
   обеспечивает.

4. **Существующий food-канал.** Игорь продолжает писать «съел пиццу» — это идёт
   в `router_food`, не в агента. Никаких изменений тут не делаем.

5. **Реестр packs не ломает существующие записи.** Pack `generic` остаётся —
   у Павла/Олега он. Добавление `respiratory_allergic` не трогает других. Тест:
   `get_pack("generic")` после изменений возвращает то же что было.

6. **`deploy.sh`/CI/cron.** Не трогаем. Никаких новых системных сервисов.

7. **Свежие коммиты.** Недавняя работа (`agent: быстрый fallback на 4.5`,
   `agent: retry на Anthropic 529/503/429`) — переиспользуется как есть. Скрипт
   делает Anthropic-вызовы через тот же helper из `core/`.

---

## 7. Полный доступ Игоря к его данным через бота

После onboarding'а Игорь должен мочь:

| Сценарий | Команда / реплика | Что под капотом |
|---|---|---|
| Спросить про последний анализ | «какой у меня был витD в последний раз?» | Agent → `/api/agent/kb_value?key=vitamin_d` |
| Динамика биомаркера | «покажи как у меня менялся витD» | Agent → `/api/agent/render_report` с marker=vitamin_d |
| Дашборд / общая сводка | «покажи мой дашборд» | Кнопка /mc/<share_token>, который уже есть для Игоря |
| Аллерго-история | «к каким аллергенам у меня реакция?» | Agent → `kb_value?key=allergy_tests` |
| Прививки | «когда последняя клещевая?» | Agent → `kb_value?key=tick_encephalitis_IgG` или `vaccinations` |
| Логирование еды | «съел пиццу» | Через router_food (как сейчас) |
| Логирование добавок | «выпил витD» | Agent → `/api/agent/log_supplement` |
| Логирование АД | «давление 120/80» | Agent → `/api/agent/log_bp` |
| Регенерация health-token | «сделай новую ссылку на дашборд» | Agent → `/api/agent/regenerate_health_token` |

**Все 8 endpoints в `agent_tools_api.py` уже работают для family-cohort.** Проверка —
запросом от имени Игоря после onboarding'а (E2E smoke в § 5.6).

---

## 8. Риски и митигации

| Риск | Митигация |
|---|---|
| LLM выдаст плохой промпт | `--dry-run` показывает результат; git-артефакт можно ручно поправить и применить через `--from-file` |
| Сетевой обрыв между scp и UPDATE | Atomic scp (.tmp+mv) + snapshot БД + автоматический rollback |
| Сервер ребутнётся во время операции | Post-flight verify (§5.6) поймает; скрипт не пишет "success" без verify |
| Игорь скажет «нет, удали» | `--unenroll` готов; privacy gate в welcome |
| KB имеет необычную структуру | Валидация (§5.2) + fallback в template для пустых блоков |
| Случайный запуск на чужом юзере | Без `--force` падает если уже enrolled; snapshot сохраняется в любом случае |
| Anthropic API недоступен | Существующий retry (529/503/429) + fallback 4.6→4.5 переиспользуется |

---

## 9. Открытые вопросы (не блокирующие)

- **Кому Игорь пишет если хочет отключиться?** Сейчас — Александру. Возможно
  стоит добавить команду `/unenroll_me` в боте, но это отдельная задача.
- **ADR-0003 про pack registry — писать?** Решение принято в этом дизайне, можно
  отложить. Если в коде окажется не очевидно зачем packs в Python — написать.
- **Welcome-сообщение Игорю — финальный текст.** Драфт в §5.7, может быть скорректирован
  в момент рассылки.

---

## 10. Hooks для будущего проекта C (self-serve onboarding)

Чтобы будущая автоматизация переиспользовала кирпичики этого проекта без переписывания:

1. **Стадии pipeline разделены в коде:**
   - `parse_raw_to_kb()` — в B не реализуем, в C появится (LLM-парсинг PDF/JPEG → JSON)
   - `validate_kb()` — в B, переиспользуется
   - `generate_persona_blocks()` — в B, переиспользуется
   - `deploy_to_server()` — в B, переиспользуется
   - `send_welcome()` — в B, переиспользуется

   C добавит первую стадию + watcher/upload-UI, остальные дёргает существующие.

2. **Скрипт принимает `--kb-path`** (default — FamilyHealth folder). C передаст
   `/tmp/parsed_kb_<tid>.json` после автопарсинга.

3. **Templates параметризованы через cohort+pack+age+style.** Расширение под
   новые комбинации не требует переписывания шаблонизатора.

4. **`--send-welcome` отделён от `--enroll`.** В C welcome придёт после approval
   юзером распарсенного KB, скрипт это поддерживает.

5. **Идемпотентность.** `--enroll` повторно с теми же входами — no-op. Это
   критично для C где watcher может триггерить много раз.

---

## 11. Definition of Done

Проект считается завершённым когда:

- [ ] Игорь успешно прошёл onboarding (cohort=family, pack=respiratory_allergic,
      KB на сервере, прoмпт в БД).
- [ ] E2E smoke: Игорь спрашивает «какой у меня последний витD?» → агент отвечает
      числом и датой из KB.
- [ ] E2E smoke: Игорь продолжает логировать еду как раньше — ничего не сломалось.
- [ ] Smoke-проверка регрессий: Павел и Андрей продолжают получать ответы агента
      с учётом своих данных (один запрос каждому через ask_agent).
- [ ] Welcome-сообщение отправлено Игорю.
- [ ] Тесты `tests/test_onboard_family_user.py` зелёные.
- [ ] Runbook `docs/operations/onboard-family-user.md` написан и проверен на
      сухом прогоне (`--dry-run` для мамы покажет понятный план).
- [ ] AI_CHANGELOG обновлён.
- [ ] Git: коммиты атомарные, в локальной ветке `main`. Push — после ревью.

---

## 12. Что дальше

После аппрува этого дизайна:
1. Создать implementation plan через writing-plans skill.
2. Имплементация в worktree (изоляция от других задач).
3. Code review через requesting-code-review skill.
4. Merge + deploy.
5. Onboarding Игоря (реальный запуск).
6. Welcome → Игорь начинает общаться.
7. Через несколько дней — onboarding мамы по тому же runbook (валидация переиспользуемости).
