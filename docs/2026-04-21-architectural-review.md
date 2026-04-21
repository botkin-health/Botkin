# Архитектурный аудит — топ-10 проблем и оптимизаций

**Дата:** 2026-04-21
**Контекст:** ревью кода и данных HealthVault бота после серии быстрых фич (фибро-пайплайн, мини-апп редизайн, supplements daily log).
**Метод:** три независимых ревьюера (Backend/Data architect, Frontend/UX architect, Pragmatic engineer) каждый посмотрел свою область + личная проверка автора через SQL-пробу 100 дней реальных данных пользователя 895655 (1300 items, 570 nutrition_log, 30 дубль-минут).

**Все 307 тестов проходят. Бот работает. Эти находки — про долгосрочную надёжность, не про срочные баги.**

---

## Tier S — данные молча гниют (исправить в первую очередь)

### #1. Три несовместимые схемы внутри `nutrition_log.items` JSONB

**Эвиденс из БД (последние 100 дней):**
```
1166 items {food, amount, unit, ...}      ← основной путь Telegram-бота (db_save.py:60)
  69 items {name, weight, quantity, ...}  ← легаси из core/food/nutrition.py:505
   0 items {product, weight_g, ...}       ← путь POST /api/meal/item (mini-app add)
```

**Что ломается молча:** `database/crud.py:703 get_recent_product_names` читает только `it.get("product")` и `it.get("weight_g")` → на 1166 items этой функции возвращает пусто → **раздел «Часто используемое» в мини-аппе при добавлении нового item беззвучно неработоспособен** для всех блюд логированных через бот (90% записей).

**Все архитекторы сошлись:** Backend нашёл проблему через grep+SQL, Frontend подтвердил что вижу через api.js debug, Pragmatic заметил 3 разных формата в helper'ах.

**Что делать:** зафиксировать ОДНУ каноническую схему `{product, weight_g, calories, protein, fats, carbs, fiber, drinks?}`. Написать миграцию переводящую все 1235 items в эту схему. Удалить fallback-цепочки `or`. Добавить Pydantic-модель которая отвергает чужие ключи на write.

**Приоритет:** P0 — текущий рост данных не остановить, чем дальше тем дороже миграция.

---

### #2. 103 items имеют ненулевые калории но `amount = null`

**Эвиденс:** ~8% записей за 100 дней. Из них чистая невозможность пересчитать порцию: `id=1099 Микро-паста с кальмарами amount=null calories=645`.

**Корень:** LLM иногда возвращает meal-level макросы без веса (особенно для составных блюд). `db_save.py:61` пишет `weight_g=0.0` что трактуется как null. `update_nutrition_item_weight` в `crud.py:614` имеет спец-кейс `old_w <= 0` который **не пересчитывает** макросы — то есть пользователь правит вес, а калории остаются те же.

**Уже частично починено:** `chatgpt_vision.py` промпт и `router.py` теперь требуют ненулевой `weight_grams`. Но проблема в том что для уже залогированных 103 items нет миграции.

**Что делать:**
1. На write — добавить `if amount is None or amount <= 0: reject` в `db_save.py`
2. Скрипт для backfill: для записей с known per-100g (можно вытащить из items.calories vs items.protein/fats/carbs) обратной арифметикой восстановить вес. Где невозможно — пометить флагом `needs_review`.

**Приоритет:** P0 — каждая такая запись отравляет дневные суммы и историческую аналитику.

---

### #3. Unique-constraint `(user_id, date, meal_time, meal_name)` бесполезен — 30 дублей за 100 дней

**Эвиденс:**
```
2026-04-17 21:29 + 2 разных meal_name (батончик + конфеты) → 2 строки
2026-03-24 23:50 + "Завтрак" + "Обед" → 2 строки
2026-03-22 12:25 + "Завтрак" + "Яблоко" → 2 строки
```

**Почему:** `meal_name` — свободный текст от LLM («Завтрак: сочник + пирог», «Яблоко»), не категория слота. Два «обеда» в одну минуту с разными названиями = два рядa.

**Последствие:** `find_meal_for_slot` возвращает первый ряд; добавление item через мини-апп пишется в одну строку, а в дневнике видно две сиблинговые карточки в одном слоте. Суммы считаются правильно (sum по строкам), но UI рваный.

**Что делать:** заменить unique-key на `(user_id, date, slot)` где slot вычисляется из meal_time. Миграция: схлопнуть same-slot ряды через JSONB concat items.

**Приоритет:** P0 — баг видим пользователю + блокирует часть фич мини-аппа.

---

### #4. `totals.fiber` дрейфует между путями записи и чтения

**Эвиденс:** 22/570 рядов (3.8%) имеют `totals.fiber` не совпадающий с `Σ items.fiber > 0.5г`. Read-time fallback в `nutrition_api.py:89` молча перезаписывает `meal_totals["fiber"] = sum_fiber(items_enriched)`. Но `get_nutrition_totals_by_date` в `crud.py:172` суммирует `log.totals.get("fiber")` **без re-enrichment** → команда `/day` бота, weekly digest и любой внешний consumer видят устаревшее значение.

**Что делать:** убрать `totals.fiber` из storage (всегда вычислять при чтении) ИЛИ добавить SQLAlchemy event-hook `before_update` который пересчитывает на каждой записи. Выбрать ОДНО.

**Приоритет:** P1 — две разные «клетчатки сегодня» в зависимости от точки входа.

---

## Tier A — UX-баги видимые пользователю

### #5. Race-condition в supplements toggle: вторая быстрая нажимка теряется

**Файл:** `index.html:898-932 toggleSupplement`

**Сценарий:** Тапнул Витамин D → optimistic flip → `await POST` → `loadSupplementsDay()` (`innerHTML = html` пересоздаёт все DOM ноды). Если за эти 300-800мс пользователь тапнул второй ряд (например Омегу), её row-элемент уничтожается при innerHTML, optimistic flip и `catch`-revert работают на уже мёртвой ноде. Хуже того, вторая ре-рендер показывает **состояние ДО второй нажимки** — визуально откатывает её, и пользователь думает что не сработало → тапает третий раз.

**Что делать:** не делать full reload после toggle. Просто инкрементить/декрементить счётчик прогресса локально. Или: request-generation counter (`if (reqId !== latestReqId) return`).

**Приоритет:** P1 — вы это увидите при ежедневном использовании.

---

### #6. Autosave: молчаливая потеря данных при таб-свитче и no-retry

**Файл:** `index.html:669-725`

**Три проблемы:**
1. **Tab-switch до blur:** на mobile Safari внутри Telegram webview тап по таб-кнопке не всегда вызывает blur на BMR-инпуте. Введённое значение остаётся в DOM, не отправлено на сервер. Нет `visibilitychange`/`beforeunload` хука который бы flush'ил.
2. **No retry on network failure:** красная пилюля «⚠ Ошибка» показывается на 1.5 сек и исчезает. Локальный `settings` уже мутирован, сервер — нет. Расхождение навсегда до следующего изменения этого же поля.
3. **No client-side validation:** битая дата → POST → 400 → пользователь не понимает какое поле виновато.

**Что делать:** `document.addEventListener('visibilitychange', flushPendingAutosave)`. Очередь dirty-полей с retry на failure. Поле-уровневые ошибки (red border + tooltip).

**Приоритет:** P1 — silent data loss — худший класс багов.

---

### #7. Autosave-pill прячется за tab-bar на iPhone с notch

**Файл:** `index.html:299-303`

**Эвиденс:**
```css
.autosave-pill { bottom: 72px; }  /* фикс, без safe-area */
.tab-bar { height: 50px + env(safe-area-inset-bottom); }  /* ~84px на iPhone Pro */
```

72 < 84 → пилюля **за** таб-баром, невидима. На устройстве с notch ты НЕ видишь подтверждения сохранения.

**Что делать:**
```css
.autosave-pill { bottom: calc(72px + env(safe-area-inset-bottom)); }
```

Заодно `.tab-panel { padding-bottom: 90px }` (сейчас 70px — впритык).

**Приоритет:** P2 — мелкая визуальная фигня, но раздражающая ежедневно.

---

## Tier B — tech debt и операционная гигиена

### #8. Мёртвый код: 6 proxy-шимов + 80 строк dead CSS + папка `archive/2026-02-01/`

**Эвиденс:**
- `core/menu_meal_processor.py`, `core/weight_extraction.py`, `core/chatgpt_vision.py`, `core/menu_parser.py`, `core/description_parser.py`, `core/ocr_weight.py` — каждый по 3 строки re-export, datelined «рефакторинг 22.03.2026». Используются только в 3 импортах в `handlers/photo.py:34,89,276`.
- В `index.html` мёртвые CSS-классы: `.tile, .tiles, .save-btn, .saved-toast, .section-title, .field-group, .slot-group, .supp-list, .supp-item, .del-btn (старый), .calc-btn, .disabled-notice` — оставлены после Phase 1-3 редизайна.
- `archive/2026-02-01/` — 228K, 18+ скриптов которые импортят из `core.ocr_weight`, `core.chatgpt_vision`. После удаления proxy-шимов сломаются. Но они никогда не запускаются — мёртвый груз в репо.

**Что делать (30 минут):**
1. Перевести 3 импорта в `photo.py` на `core.vision.*` / `core.food.*` напрямую
2. `rm core/menu_meal_processor.py core/weight_extraction.py core/chatgpt_vision.py core/menu_parser.py core/description_parser.py core/ocr_weight.py`
3. `rm -rf archive/2026-02-01/`
4. Удалить 80 строк dead CSS из inline `<style>` в `index.html`

**Приоритет:** P2 — не срочно но при попытке рефакторинга путает.

---

### #9. AI-context документы устарели на 5+ недель — Claude читает и врёт

**Эвиденс:**
- `docs/ai_context/01_architecture.md` — 1 марта (50 дней)
- `docs/ai_context/03_database_schema.md` — 10 марта. **НЕ упоминает `user_settings`, `supplements_log`, `weights`, `activity_log`** — описывает только `users` и `nutrition_log`.
- `docs/ai_context/04_workflows.md` — 14 апреля. Пути модулей устарели: `core/llm_router.py` (фактически `core/llm/router.py`).
- `docs/ai_context/FULL_CONTEXT.md` — 14 марта. Не знает про мини-апп (5 апреля), фибро-пайплайн (2 апреля), nutrition day editor (17 апреля), редизайн (19 апреля), supplements API (21 апреля).

**Что делать:** либо переписать (45 минут), либо удалить устаревшие. `AI_CHANGELOG.md` (свежий, 6 дней) — единственный источник правды. Можно сделать его main entry point и удалить overlapping старьё.

**Приоритет:** P1 — каждая моя сессия начинается с чтения этих файлов и я получаю неверную картину архитектуры.

---

### #10. `handlers/photo.py` 1217 строк — ноль покрытия тестами

**Эвиденс:** `grep -l "handlers/photo" tests/` → пусто. Из 307 тестов **ни один** не трогает фото-флоу. А это самый сложный путь — менюшный OCR, фото-блюд, фото-упаковок, фото весов с показанием.

**Что ломается без тестов:** все наши фиксы про fiber, weight_grams, schemas, дата-парсинг — ни один не покрыт интеграционным тестом для фото-пути. При следующем рефакторинге сломается тихо.

**Что делать:** добавить хотя бы smoke-тест который мокает `bot.download_file`, `chatgpt_vision`, и проверяет что handler не падает на каждом branch'е (menu / food / weight / vision-error / no-text). 1-2 часа.

**Приоритет:** P1 — единственный critical-mass файл без safety net.

---

## Бонус: что я видел но не вошло в топ-10

- **Алкоголь не учитывается в макросах**: 36 items имеют макро-vs-калории mismatch, все алкоголь. Этанол ~7 ккал/г не вписан в P/F/C, downstream аналитика искажается на 300-500 ккал/неделя в дни с выпивкой. Нужен `alcohol_g` отдельный.
- **Garmin sync блокирует request loop** в `/api/day` (до 2 сек задержки на «сегодня»).
- **Pydantic V2 deprecation warnings** в `services/state_models.py` (3 шт) и `datetime.utcnow()` в `crud.py:581`. Сейчас warning, в Pydantic v3 будут errors.
- **`requirements.prod.txt` без `fastapi`/`uvicorn`** — если он реально используется в проде, webhooks 500'ят. Скорее всего не используется (есть `requirements.txt`), но тогда удалить файл во избежание путаницы.
- **3 docker-compose файла** (yml/dev/prod) без явной документации какой канонический.
- **Backup retention** — `data/backups/` 81 МБ, 10 файлов, рос монотонно. Нужно `find -mtime +30 -delete` в /cleanup.
- **Доступность мини-аппа** — `.del-btn-round` 22×22px меньше iOS HIG 44pt. Зелёный pill контраст 2.9 — fail WCAG AA.
- **HEALTH.md / KNOWLEDGE_BASE.md** старше `knowledge_base.json` на 6 дней — не синхронизируются автоматически.

---

## Финальный вердикт трёх архитекторов

**Backend архитектор:** «Schema drift и null weights — это утечка качества данных. Чем дольше живёт сейчас тем дороже будет миграция. Делать первым.»

**Frontend архитектор:** «Toggle race и autosave silent loss видны пользователю каждый день. UI bugs > tech debt по приоритету.»

**Pragmatic engineer:** «Мёртвый код и стейл доки тянут вниз скорость каждой следующей задачи. Чистка за 30-45 минут окупится за 2 недели.»

**Сошлись на:** делать в три захода:

| Заход | Что | Время |
|---|---|---|
| **1 (быстрый)** | #8 dead code + #9 docs обновить + #7 pill safe-area | ~2 часа |
| **2 (важный)** | #1 schema migration + #2 null weights backfill + #3 unique key fix | ~1 день |
| **3 (надёжность)** | #5 race fix + #6 autosave robustness + #10 photo.py тесты | ~1 день |

Не хвататься за всё сразу. Делать по одному пункту, тестировать. Все находки воспроизведены через grep и SQL-пробу — гипотез нет.

---

*Документ сгенерирован Claude Sonnet 4.6 в режиме мультиагентного аудита. 3 параллельных агента + сводный анализ. Время работы ~7 минут, ~250k токенов суммарно.*
