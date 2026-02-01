# Команды для автобэкапа HealthVault БД

## Ручные команды

```bash
# Создать бэкап сейчас
make db-backup

# Восстановить из последнего бэкапа
make db-restore
# > Выберите 'latest'

# Восстановить из конкретного файла
make db-restore
# > Введите имя файла (например: healthvault_2026-02-01_133459.sql)
```

## Автоматический бэкап (Cron)

### Установка

1. Откройте crontab:
```bash
crontab -e
```

2. Добавьте строку:
```bash
# Автобэкап HealthVault БД каждый день в 3:00 UTC
0 3 * * * cd /Users/alexlyskovsky/HealthVault && make db-backup-auto >> backup/cron.log 2>&1
```

3. Сохраните и выйдите (`:wq` в vim)

### Проверка

```bash
# Посмотреть текущие задачи cron
crontab -l

# Проверить лог автобэкапа
cat backup/cron.log
```

### Детали `db-backup-auto`

- Создает бэкап: `backup/healthvault_YYYY-MM-DD.sql`
- Удаляет бэкапы старше 7 дней
- Экономит место на диске

## Восстановление после сбоя

Если Postgres поврежден или потеряны данные:

```bash
# 1. Остановить бота и БД
pkill -f bot.py
make db-down

# 2. Поднять чистую БД
make db-up

# 3. Восстановить из последнего бэкапа
make db-restore
# > Выберите 'latest'

# 4. Проверить данные
make db-shell
# > SELECT COUNT(*) FROM weight_logs;

# 5. Запустить бота
make run-fast
```

## Где хранятся бэкапы

- **Директория:** `backup/`
- **Формат:** `healthvault_YYYY-MM-DD_HHMMSS.sql` (ручной)
- **Формат:** `healthvault_YYYY-MM-DD.sql` (auto)
- **Срок хранения:** 7 дней (auto), бесконечно (ручной)

## .gitignore

Убедитесь что `/backup` в `.gitignore` (уже есть ✅)
