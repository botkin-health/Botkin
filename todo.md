
# Roadmap

- [ ] **1. База знаний по добавкам (Приоритет: Сегодня)**
    - [ ] Составить список (похудение, тестостерон, энергия, холестерин)
    - [ ] Интегрировать в `HEALTH.md` и базу бота

- [ ] **2. Бот: Трекинг добавок (Приоритет: Сегодня)**
    - [ ] Модель данных "Склад" и "Потребление"
    - [ ] Команды чекина (текст/фото) с обновлением остатков

- [ ] **3. Голосовой ввод (Приоритет: Сегодня)**
    - [ ] Распознавание голоса (Whisper/Telegram API)
    - [ ] Парсинг съеденного из текста

- [x] **Snapshot Testing for Nutrition Data**
    - [x] Create test fixtures for nutrition data (10 variants based on recent logs)
    - [x] exact match verification logic

- [ ] **Apple Health Integration**
    - [ ] Implement API endpoint for data ingestion (weight, steps, active calories)
    - [ ] Create automation manual for iOS Shortcuts


- [ ] **Server Deployment (24/7 Availability)**
    - [ ] Create `DEPLOY.md` with VPS instructions
    - [ ] Configure systemd/Docker for auto-restart
    - [ ] Setup remote data access (or sync)

- [ ] **Reporting Improvements**
    - [ ] **Daily Status**: Simplify to show N meals, Total Calories/Macros, Remaining vs Target (considering deficit avg).
    - [ ] **Weekly Analysis**: Summary of last 7 days, deficits/surpluses, specific nutrient recommendations.

- [ ] **Multi-user Support & Auth**
    - [ ] Implement user authorization (whitelist or password)
    - [ ] Isolate data per user (separate `knowledge_base` / `nutrition_log` paths)
    - [ ] Configurable storage location per user

- [ ] **Architectural Refactoring**
    - [ ] Extract shared logic into `health_lib` or `core`
    - [ ] Update `telegram-bot` and `scripts` to use shared library

- [ ] **Stress Testing (Chaos Monkey)**
    - [ ] Generate 100 days of nutrition data
    - [ ] Generate "broken" export files for parsers
    - [ ] Verify error handling

- [ ] **File Migration to Google Drive**
    - [ ] Move `/Users/alexlyskovsky/HealthVault/data` contents to Google Drive
    - [ ] Keep `knowledge_base.json` and project code in current location
