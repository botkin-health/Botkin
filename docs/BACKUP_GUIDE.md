# Бэкапы Botkin / HealthVault БД

> Стратегия 3-2-1: 3 копии (живая БД + локальный `.gz` + облако), 2 носителя,
> 1 копия offsite (Google Drive). Внедрено 06.06.2026.

## Где что лежит

| Слой | Путь | Ротация |
|---|---|---|
| Живая БД | контейнер `healthvault_postgres` (Hetzner) | — |
| Локальные дампы | `/opt/backups/healthvault_<TS>.sql.gz` | 14 последних |
| Offsite daily | `FamilyHealth/_backups_db/daily/` | 30 дней |
| Offsite weekly | `FamilyHealth/_backups_db/weekly/` (по воскресеньям) | 56 дней (8 шт) |
| Offsite monthly | `FamilyHealth/_backups_db/monthly/` (1-го числа) | 365 дней (12 шт) |

Offsite лежит в личном «Мой диск» рядом с ручными снимками (`_backups_db/`),
синкается на мак Александра.

⚠️ **Подводный камень rclone:** remote `gdrive:` на сервере по умолчанию
скоупнут на КОРПОРАТИВНЫЙ корень iFarm (`root_folder_id=1Uetbu…`), а не на
личный My Drive. Скрипт переопределяет это через `RCLONE_DRIVE_ROOT_FOLDER_ID=root`.
Без этой переменной бэкапы уезжают в чужой корпоративный FamilyHealth (утечка
данных). Любые ручные `rclone`-команды к личному диску — тоже с этим флагом:
`rclone --drive-root-folder-id=root ls gdrive:FamilyHealth/_backups_db/daily`.

## Что попадает в дамп

`pg_dump` всей БД `healthvault` — 15 таблиц, включая **данные пользователей**
(`users`, `nutrition_log`, `blood_tests`, `blood_pressure_logs`, `weights`,
`sleep_records`, `activity_log`, `supplements_log`) и **логи**
(`agent_conversations` — переписка с ботом, `audit_log`, `llm_usage_log`).

⚠️ Медиа (`data/media/` — фото еды, голосовые) в дамп **не входят** — бэкапятся
отдельно при необходимости (см. todo).

## Автоматизация (cron на сервере)

```cron
30 3 * * *  /usr/local/bin/healthvault_backup.sh        # ежедневный бэкап + offsite + GFS
0  4 1 * *  /usr/local/bin/healthvault_restore_test.sh  # ежемесячный drill восстановления
```

Канонические версии скриптов — в репо `scripts/server/`. После правок —
залить на сервер в `/usr/local/bin/` (scp) и `chmod +x`.

Лог обоих: `/var/log/healthvault_backup.log`.

## Ручные команды

```bash
# сделать бэкап сейчас (включая offsite)
/usr/local/bin/healthvault_backup.sh

# прогнать тест восстановления вручную
/usr/local/bin/healthvault_restore_test.sh

# посмотреть последние записи лога
tail -20 /var/log/healthvault_backup.log

# список облачных копий (флаг root обязателен — см. подводный камень выше)
rclone --drive-root-folder-id=root ls gdrive:FamilyHealth/_backups_db/daily
```

Через админку (botkin.health/admin) — кнопка «Сделать бэкап сейчас» делает
локальный дамп (offsite добавляется крон-скриптом).

## Восстановление после сбоя

```bash
# 1. взять свежий дамп (локальный или из облака)
LATEST=$(ls -t /opt/backups/healthvault_*.sql.gz | head -1)
# из облака при потере сервера:
#   rclone --drive-root-folder-id=root copy gdrive:FamilyHealth/_backups_db/daily/<файл>.sql.gz ./

# 2. развернуть в БД (ОСТОРОЖНО: перетирает данные)
zcat "$LATEST" | docker exec -i healthvault_postgres psql -U healthvault -d healthvault

# 3. проверить
docker exec healthvault_postgres psql -U healthvault -d healthvault \
  -c "SELECT count(*) FROM users; SELECT count(*) FROM nutrition_log;"
```

Безопасная проверка дампа без риска для прода — `healthvault_restore_test.sh`
(разворачивает в одноразовую БД и удаляет её).

## Проверка здоровья бэкапов

- `tail /var/log/healthvault_backup.log` — есть ли строки `backup created`,
  `offsite daily OK`, ежемесячно `restore OK`.
- Если видишь `ERROR: offsite ... FAILED` — проверить `rclone listremotes` и
  токен gdrive (`rclone about gdrive:`).

---

[← Документация Botkin — Index](INDEX.md)
