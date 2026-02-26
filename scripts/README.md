# Скрипты HealthVault

## Миграция и заливка в БД (на сервере)

Запуск в контейнере: `docker exec -e PYTHONPATH=/app healthvault_bot python scripts/<скрипт>.py`

| Скрипт | Назначение |
|--------|------------|
| `migrate_nutrition_to_db.py` | Один раз: перенос питания из `data/nutrition/nutrition_log.json` в таблицу `nutrition_log`. Дубликаты пропускаются. |
| `migrate_weights_to_db.py` | Перенос весов из `data/weights/*.json` (в т.ч. Apple Health) в таблицу `weights`. |
| `migrate_garmin_from_json.py` | Перенос активности и сна из `data/garmin/daily-summary/*.json` в `activity_log`. |
| `backfill_sleep_from_garmin.py` | Дозаполнение сна из `data/garmin/sleep/*.json` для дней без записи сна в БД. |
| `backfill_weight_carry_forward.py` | Для дней без замера веса создаёт запись с последним известным весом (`source=carry_forward`). |

## Проверка покрытия

| Скрипт | Назначение |
|--------|------------|
| `coverage_report.py` | Отчёт по датам с 2026-01-06: питание, вес, витамины, активность, сон. |

## Остальные

- `garmin/download_garmin_data.py` — выгрузка данных из Garmin Connect в `data/garmin/`.
- `apple-health/` — обработка экспорта Apple Health.
- `validate_json.py` — проверка JSON (только существующих файлов).
- Анализ: `analyze_health_correlations.py`, `check_data_coverage.py`, `analyze_bp_correlations.py` и др. — могут ссылаться на локальные JSON; при необходимости использовать выгрузки с сервера (`nutrition_log_remote.json` и т.д.).
