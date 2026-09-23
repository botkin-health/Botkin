#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Botkin / HealthVault — резервное копирование БД (local + offsite + GFS).
#
# Деплоится на прод-сервер как /usr/local/bin/healthvault_backup.sh
# Cron: 30 3 * * *  /usr/local/bin/healthvault_backup.sh
#
# Делает:
#   1) pg_dump | gzip → /opt/backups/healthvault_<TS>.sql.gz
#   1b) файлы пользователей (data/uploads — сканы из /doc и сохранённые
#       документы профиля; data/kb — их список documents[]) → botkin_files_<TS>.tar.gz
#   2) локальная ротация — 14 последних
#   3) offsite-копия на Google Drive (rclone remote gdrive:) — daily
#   4) GFS: по воскресеньям → weekly, 1-го числа → monthly
#   5) облачная ротация: daily 30д, weekly 56д, monthly 365д
#
# Правило 3-2-1: 3 копии (БД + локальный .gz + облако), 2 носителя, 1 offsite.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

TS=$(date +%Y%m%d_%H%M%S)
DOW=$(date +%u)   # 1..7 (7 = воскресенье)
DOM=$(date +%d)   # 01..31

LOCAL_DIR=/opt/backups
# Offsite — в ЛИЧНЫЙ «Мой диск» Александра, папка FamilyHealth/_backups_db
# (там же ручные снимки + README, синкается на мак).
# ВАЖНО: remote gdrive: по умолчанию скоупнут на КОРПОРАТИВНЫЙ корень iFarm
# (root_folder_id=1Uetbu…). Чтобы попасть в личный My Drive, переопределяем
# root на "root" (алиас My Drive в Drive API). Без этой строки бэкапы уезжают
# в чужой корпоративный FamilyHealth — прецедент 06.06.2026.
export RCLONE_DRIVE_ROOT_FOLDER_ID=root
# GFS идёт в подпапки daily/weekly/monthly; ротация бьёт только по ним,
# ручные дампы в корне _backups_db не трогаются.
RCLONE_REMOTE="gdrive:FamilyHealth/_backups_db"
LOG=/var/log/healthvault_backup.log
KEEP_LOCAL=14

BACKUP="$LOCAL_DIR/healthvault_${TS}.sql.gz"
FILES_BACKUP="$LOCAL_DIR/botkin_files_${TS}.tar.gz"
DATA_DIR=/opt/botkin/data

log() { echo "$(date -Iseconds) $*" >> "$LOG"; }

mkdir -p "$LOCAL_DIR"

# 1) dump ─────────────────────────────────────────────────────────────────────
docker exec healthvault_postgres pg_dump -U healthvault healthvault | gzip > "$BACKUP"
if [ ! -s "$BACKUP" ]; then
    log "ERROR: дамп пустой/не создан ($BACKUP) — прерываю, старый бэкап не трогаю"
    rm -f "$BACKUP"
    exit 1
fi
SIZE=$(ls -lh "$BACKUP" | awk '{print $5}')
log "backup created: $(basename "$BACKUP") ($SIZE)"

# 1b) файлы пользователей ───────────────────────────────────────────────────────
# До 23.09.2026 в бэкап попадала только БД: сканы из /doc и kb_<id>.json с их
# списком жили на диске сервера без копии. Сбой архива файлов НЕ отменяет
# бэкап БД — пишем ошибку в лог и идём дальше.
if tar -czf "$FILES_BACKUP" -C "$DATA_DIR" uploads kb 2>>"$LOG" && [ -s "$FILES_BACKUP" ]; then
    log "files backup created: $(basename "$FILES_BACKUP") ($(ls -lh "$FILES_BACKUP" | awk '{print $5}'))"
else
    log "ERROR: архив файлов не создан ($FILES_BACKUP)"
    rm -f "$FILES_BACKUP"
fi

# 2) локальная ротация — KEEP_LOCAL последних ───────────────────────────────────
ls -t "$LOCAL_DIR"/healthvault_*.sql.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f
ls -t "$LOCAL_DIR"/botkin_files_*.tar.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f

# 3) offsite — daily ───────────────────────────────────────────────────────────
if rclone copy "$BACKUP" "$RCLONE_REMOTE/daily/" 2>>"$LOG"; then
    log "offsite daily OK → $RCLONE_REMOTE/daily/$(basename "$BACKUP")"
else
    log "ERROR: offsite daily upload FAILED (rclone)"
fi
if [ -s "$FILES_BACKUP" ]; then
    if rclone copy "$FILES_BACKUP" "$RCLONE_REMOTE/daily/" 2>>"$LOG"; then
        log "offsite daily files OK → $RCLONE_REMOTE/daily/$(basename "$FILES_BACKUP")"
    else
        log "ERROR: offsite daily files upload FAILED (rclone)"
    fi
fi

# 4) GFS: weekly (воскресенье) / monthly (1-е число) ────────────────────────────
if [ "$DOW" = "7" ]; then
    rclone copy "$BACKUP" "$RCLONE_REMOTE/weekly/"  2>>"$LOG" && log "offsite weekly OK"
    [ -s "$FILES_BACKUP" ] && rclone copy "$FILES_BACKUP" "$RCLONE_REMOTE/weekly/" 2>>"$LOG" && log "offsite weekly files OK"
fi
if [ "$DOM" = "01" ]; then
    rclone copy "$BACKUP" "$RCLONE_REMOTE/monthly/" 2>>"$LOG" && log "offsite monthly OK"
    [ -s "$FILES_BACKUP" ] && rclone copy "$FILES_BACKUP" "$RCLONE_REMOTE/monthly/" 2>>"$LOG" && log "offsite monthly files OK"
fi

# 5) облачная ротация по возрасту ───────────────────────────────────────────────
rclone delete --min-age 30d  "$RCLONE_REMOTE/daily/"   2>>"$LOG"
rclone delete --min-age 56d  "$RCLONE_REMOTE/weekly/"  2>>"$LOG"
rclone delete --min-age 365d "$RCLONE_REMOTE/monthly/" 2>>"$LOG"

log "done"
