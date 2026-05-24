#!/bin/bash
# Botkin: единый pull-sync на сервере.
#
# Запускает все pull-источники последовательно, с обработкой ошибок:
# если один упал — следующие продолжают, в конце выводится сводка.
#
# Запускается изнутри контейнера healthvault_bot. Cron на хосте:
#   5 4 * * * docker exec healthvault_bot bash /app/scripts/server/sync_all.sh >> /var/log/botkin_sync.log 2>&1
#
# Логи смотрятся одной командой:
#   ssh root@server 'tail -50 /var/log/botkin_sync.log'
#
# Не путать с scripts/sync_all_data.sh — тот живёт на Маке и делает
# ОБРАТНУЮ операцию (тянет данные с сервера на Mac для локальной аналитики).
#
# Чтобы добавить новый pull-источник: дописать строку run в блок ниже.

set -u

echo "=========================================="
echo "🔄 Botkin sync run: $(date -u +%Y-%m-%d\ %H:%M:%S) UTC"
echo "=========================================="

declare -A RESULTS
declare -a ORDER

run() {
    local name=$1
    local script=$2
    ORDER+=("$name")

    echo ""
    echo "--- $name ($script) ---"
    if [ ! -f "$script" ]; then
        echo "❌ Script not found"
        RESULTS[$name]="❌ no script"
        return
    fi

    local start=$(date +%s)
    if python "$script" 2>&1; then
        local dur=$(($(date +%s) - start))
        RESULTS[$name]="✅ ${dur}s"
    else
        local dur=$(($(date +%s) - start))
        RESULTS[$name]="❌ ${dur}s"
    fi
}

run weather  /app/scripts/import/weather.py
run netatmo  /app/scripts/import/netatmo.py
# Derived: пересобирает /app/telegram-bot/env_data_{user_id}.json из
# netatmo_history.json для блока «Воздух дома» на дашборде. ОБЯЗАТЕЛЬНО после
# netatmo. Раньше этот шаг делался только в мак-pipeline (push_netatmo_to_container.py).
run env      /app/scripts/util/build_env_data.py
run garmin   /app/scripts/garmin/download_garmin_data.py
# Derived: пересобирает /app/telegram-bot/workouts_log_{user_id}.json из
# сырых Garmin-активностей, чтобы дашборд видел свежие тренировки. ОБЯЗАТЕЛЬНО
# после garmin. Раньше этот шаг делался только в мак-pipeline → дашборд отставал.
run workouts /app/scripts/util/build_workouts_log.py
# Postgres backfill: workouts + sleep + hrv в БД (для агента /recent_workouts,
# /recent_activity). Раньше эту работу делал scripts/backfill_to_postgres.py
# с мака — и протух 16-24.05.2026 потому что мак не запускали. Теперь сервер
# делает сам каждую ночь. Идемпотентно: ON CONFLICT DO NOTHING / UPDATE.
run pg_sync  /app/scripts/util/server_backfill_postgres.py

# Zepp пока отключён — токен на сервере устарел, нужен reauth с Mac
# Когда токен обновится, раскомментировать:
# run zepp /app/scripts/import/zepp_api.py

echo ""
echo "=========================================="
echo "📊 Summary"
echo "=========================================="
for name in "${ORDER[@]}"; do
    printf "  %-10s %s\n" "$name" "${RESULTS[$name]}"
done
echo "=========================================="
echo "End: $(date -u +%Y-%m-%d\ %H:%M:%S) UTC"
echo ""
