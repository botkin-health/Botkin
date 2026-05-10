#!/bin/bash
# Пушит данные Garmin daily-summary из локальных JSON-файлов в activity_log на сервере.
# Запускается как часть sync_all_data.sh после скачивания данных Garmin.
#
# Источник: data/garmin/daily-summary/YYYY-MM-DD.json (stats.activeKilocalories и др.)
#           data/garmin/hrv/YYYY-MM-DD.json (hrvSummary.lastNightAvg)
# Цель:     activity_log на сервере (healthvault_postgres) через SSH psql
#
# НЕ логинится в Garmin API — только читает уже скачанные файлы.

SERVER="root@116.203.213.137"
PASS="SERVER_PASSWORD_REDACTED"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
SUMMARY_DIR="$DIR/data/garmin/daily-summary"
HRV_DIR="$DIR/data/garmin/hrv"
USER_ID=895655

if [ ! -d "$SUMMARY_DIR" ]; then
    echo "⚠️  Папка $SUMMARY_DIR не найдена"
    exit 1
fi

echo "📤 Пуш Garmin daily-summary + HRV → activity_log на сервере..."

pushed=0
skipped=0

for json_file in "$SUMMARY_DIR"/2026-*.json; do
    [ -f "$json_file" ] || continue
    date_str=$(basename "$json_file" .json)

    # HRV-файл для той же даты (может отсутствовать)
    hrv_file="$HRV_DIR/$date_str.json"

    # Читаем поля из JSON через python (daily-summary + hrv)
    # sleep_hours = stats.sleepingSeconds (включает и main sleep, и naps — корректно для аналитики)
    read -r active bmr total steps dist hr stress hrv sleep_h <<< $(python3 -c "
import json, sys
try:
    d = json.load(open('$json_file'))
    s = d.get('stats', {})
    def iv(x): return int(x) if x is not None else 'NULL'
    def fv(x): return round(x/1000.0, 3) if x else 'NULL'

    # HRV from separate file
    hrv = 'NULL'
    import os
    hrv_path = '$hrv_file'
    if os.path.exists(hrv_path):
        try:
            hd = json.load(open(hrv_path))
            v = hd.get('hrvSummary', {}).get('lastNightAvg')
            if v is not None:
                hrv = int(v)
        except Exception:
            pass

    # sleep_hours: stats.sleepingSeconds → часы (включает main sleep + все naps)
    sleep_sec = s.get('sleepingSeconds') or s.get('measurableAsleepDuration')
    sleep_h = round(sleep_sec / 3600.0, 2) if sleep_sec else 'NULL'

    print(
        iv(s.get('activeKilocalories')),
        iv(s.get('bmrKilocalories')),
        iv(s.get('totalKilocalories')),
        s.get('totalSteps') or 'NULL',
        fv(s.get('totalDistanceMeters')),
        s.get('restingHeartRate') or 'NULL',
        s.get('averageStressLevel') or 'NULL',
        hrv,
        sleep_h
    )
except Exception as e:
    print('NULL NULL NULL NULL NULL NULL NULL NULL NULL')
" 2>/dev/null)

    # Пропускаем строки где все NULL
    if [ "$active" = "NULL" ] && [ "$steps" = "NULL" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    # Пропускаем неполные дни (часы на зарядке, ранний sync) — total < 1500
    if [ "$total" != "NULL" ] && [ "$total" -lt 1500 ] 2>/dev/null; then
        skipped=$((skipped + 1))
        continue
    fi

    # Upsert в activity_log (включая hrv + sleep_hours)
    SQL="INSERT INTO activity_log (user_id, date, active_calories, bmr_calories, total_calories, steps, distance_km, heart_rate_avg, stress_level, hrv, sleep_hours, source)
VALUES ($USER_ID, '$date_str', ${active}, ${bmr}, ${total}, ${steps}, ${dist}, ${hr}, ${stress}, ${hrv}, ${sleep_h}, 'garmin_json')
ON CONFLICT (user_id, date) DO UPDATE SET
    active_calories  = COALESCE(EXCLUDED.active_calories,  activity_log.active_calories),
    bmr_calories     = COALESCE(EXCLUDED.bmr_calories,     activity_log.bmr_calories),
    total_calories   = COALESCE(EXCLUDED.total_calories,   activity_log.total_calories),
    steps            = COALESCE(EXCLUDED.steps,            activity_log.steps),
    distance_km      = COALESCE(EXCLUDED.distance_km,      activity_log.distance_km),
    heart_rate_avg   = COALESCE(EXCLUDED.heart_rate_avg,   activity_log.heart_rate_avg),
    stress_level     = COALESCE(EXCLUDED.stress_level,     activity_log.stress_level),
    hrv              = COALESCE(EXCLUDED.hrv,              activity_log.hrv),
    sleep_hours      = COALESCE(EXCLUDED.sleep_hours,      activity_log.sleep_hours),
    source           = 'garmin_json'
WHERE activity_log.source != 'manual';"

    result=$(/opt/homebrew/bin/sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
        "docker exec healthvault_postgres psql -U healthvault -d healthvault -t -c \"$SQL\"" 2>/dev/null)

    pushed=$((pushed + 1))
done

echo "✅ Garmin → DB: $pushed дней обновлено, $skipped пропущено (нет данных)"

# Копируем garth-токены на сервер — чтобы бот мог авторизоваться в Garmin API
# без пароля (garth использует OAuth2 refresh token, живёт ~28 дней).
GARTH_LOCAL="$DIR/data/cache/garth_tokens"
GARTH_REMOTE="/opt/healthvault/data/garth/$USER_ID"
if [ -f "$GARTH_LOCAL/oauth1_token.json" ] && [ -f "$GARTH_LOCAL/oauth2_token.json" ]; then
    /opt/homebrew/bin/sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $GARTH_REMOTE"
    /opt/homebrew/bin/sshpass -p "$PASS" scp -o StrictHostKeyChecking=no \
        "$GARTH_LOCAL/oauth1_token.json" \
        "$GARTH_LOCAL/oauth2_token.json" \
        "$SERVER:$GARTH_REMOTE/" 2>/dev/null
    echo "🔑 Garth-токены обновлены на сервере"
else
    echo "⚠️  Garth-токены не найдены в $GARTH_LOCAL — пропущено"
fi
