#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Botkin / HealthVault — ежемесячный drill восстановления.
#
# Деплоится на прод как /usr/local/bin/healthvault_restore_test.sh
# Cron: 0 4 1 * *  /usr/local/bin/healthvault_restore_test.sh
#
# Берёт свежий локальный дамп, разворачивает в одноразовую БД ВНУТРИ того же
# postgres-контейнера, проверяет что таблицы/строки на месте, затем удаляет
# тестовую БД. Непроверенный бэкап = лотерея — этот скрипт убирает лотерею.
# Результат пишется в тот же лог, что и бэкап.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

LOG=/var/log/healthvault_backup.log
PG=healthvault_postgres
log() { echo "$(date -Iseconds) [restore-test] $*" >> "$LOG"; }

NEWEST=$(ls -t /opt/backups/healthvault_*.sql.gz 2>/dev/null | head -1)
if [ -z "$NEWEST" ]; then
    log "ERROR: бэкапы не найдены в /opt/backups"
    exit 1
fi

TESTDB="restore_test_$(date +%s)"
docker exec "$PG" psql -U healthvault -c "DROP DATABASE IF EXISTS $TESTDB;"  >/dev/null 2>>"$LOG"
docker exec "$PG" psql -U healthvault -c "CREATE DATABASE $TESTDB;"          >/dev/null 2>>"$LOG"

# загрузка дампа в тестовую БД
zcat "$NEWEST" | docker exec -i "$PG" psql -U healthvault -d "$TESTDB" >/dev/null 2>>"$LOG"

q() { docker exec "$PG" psql -U healthvault -d "$TESTDB" -tAc "$1" 2>>"$LOG" | tr -d '[:space:]'; }
TBLS=$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
USERS=$(q "SELECT count(*) FROM users;")
NUTR=$(q "SELECT count(*) FROM nutrition_log;")

docker exec "$PG" psql -U healthvault -c "DROP DATABASE $TESTDB;" >/dev/null 2>>"$LOG"

if [ "${TBLS:-0}" -ge 10 ] && [ "${USERS:-0}" -ge 1 ]; then
    log "restore OK from $(basename "$NEWEST"): tables=$TBLS users=$USERS nutrition=$NUTR"
else
    log "ERROR: restore verification FAILED from $(basename "$NEWEST"): tables=$TBLS users=$USERS nutrition=$NUTR"
fi
