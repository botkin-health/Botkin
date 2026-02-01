# 📊 Инвентаризация scripts/

**Дата:** 2026-02-01  
**Всего файлов:** 24 Python-скрипта + 2 Shell-скрипта + `.exp` файлы в корне

---

## Классификация

### ✅ АКТИВНЫЕ (используются регулярно)
- `validate_health_data.py` — валидация данных (обязательная процедура по README)
- `analyze_bp_correlations.py` — анализ давления (создан недавно)
- `fix_visceral_fat_bulk.py` — исправление данных весов (только что использован)
- `backfill_garmin.py` — синхронизация Garmin
- `create_backup.sh` — бэкап данных
- `check_db.sh` — проверка БД

### ⚠️ LEGACY (устаревшие/дублирующие)
- `apple_health_parser.py` — дубль? (есть `scripts/apple-health/`)
- `fixed_apple_health_analyzer.py` — "fixed" версия (временная?)
- `extract_health_data_chatgpt.py` — старый метод (до Gemini?)
- `google_vision_ocr.py` — старый OCR (теперь в `core/gemini_vision.py`)
- `integrate_apple_health.py` — возможно устарел
- `analyze_2025.py` — одноразовый анализ за конкретный год

### 🧹 ОДНОРАЗОВЫЕ/ТЕСТОВЫЕ
- `fix_nutrition_log.py` — разовая миграция
- `fix_photo_names.py` — разовая чистка
- `migrate_to_gdrive.py` — разовая миграция (выполнена)
- `migrate_to_postgres.py` — WIP (не завершена)
- `print_keys.py` — дебаг-утилита
- `test_voice_integration.py` — тест
- `verify_openai_key.py` — тест
- `verify_refactor.py` — тест после рефакторинга
- `calculate_age.py` — одноразовая утилита
- `process_downloads.py` — обработка загрузок
- `process_new_uploads.py` — обработка файлов
- `reprocess_weights.py` — разовая перегенерация

### 🔥 `.exp` файлы (корень проекта)
- `cleanup_old_server.exp`
- `deploy_to_new_server.exp`
- `fast_deploy.exp`
- `migrate_data_from_remote.exp`
- `setup_new_server.exp`

**Статус:** Скорее всего устарели (миграция на новый сервер завершена).

---

## Рекомендации к архивации

**Кандидаты на перенос в `archive/2026-02-01/`:**
1. Все `.exp` файлы (5 шт)
2. Legacy-скрипты (8 шт)
3. Одноразовые fix/migrate (7 шт)

**Итого:** ~20 файлов → archive.

**Сохранить:** 6 активных скриптов.
