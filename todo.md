
# Roadmap

- [x] **3. Голосовой ввод**
    - [x] Распознавание голоса (Whisper/Telegram API)
    - [x] Парсинг съеденного из текста

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

- [x] **Reporting Improvements**
    - [x] **Daily Status**: Simplify to show N meals, Total Calories/Macros, Remaining vs Target (considering deficit avg).
    - [x] **Weekly Analysis**: Summary of last 7 days, deficits/surpluses, specific nutrient recommendations.

- [ ] **Multi-user Support & Auth**
    - [ ] Implement user authorization (whitelist or password)
    - [ ] Isolate data per user (separate `knowledge_base` / `nutrition_log` paths)
    - [ ] Configurable storage location per user

- [x] Create comprehensive backup
- [x] Refactor module structure
    - [x] Create `core` package
    - [x] Move shared logic (`nutrition`, `storage`, etc.)
    - [x] Standardize data paths to `HealthVault/data`
- [x] Update import paths in Bot and Scripts
- [x] Verify functionality
    - [x] Develop verification script
    - [x] Test photo/text/voice flows
- [x] Generate final report (Russian)

- [ ] **Stress Testing (Chaos Monkey)**
    - [ ] Generate 100 days of nutrition data
    - [ ] Generate "broken" export files for parsers
    - [ ] Verify error handling

- [x] **File Migration to Google Drive**
    - [x] Move `/Users/alexlyskovsky/HealthVault/data` contents to Google Drive
    - [x] Keep `knowledge_base.json` and project code in current location
