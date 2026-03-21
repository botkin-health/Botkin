#!/bin/bash
# Синхронизация всех источников данных HealthVault в локальную файловую систему
# ИИ-Агенты (Cursor, Claude, Antigravity) ОБЯЗАНЫ запускать этот скрипт первым делом,
# чтобы получить свежий 100% срез по питанию, сну, шагам, весам и климату из всех источников.
#
# Альтернатива: скилл /sync (автоматически вызывает этот скрипт + показывает таблицу актуальности).

echo "================================================="
echo "🔄 HealthVault: Master Data Sync"
echo "================================================="

cd "$(dirname "$0")/.." || exit 1

echo "1/4 📥 Синхронизация БД с удаленного сервера (Nutrition, Weights, Activity, Supplements)..."
export SSHPASS="SERVER_PASSWORD_REDACTED"
sshpass -e scp -o StrictHostKeyChecking=no scripts/sync_remote_db.py root@116.203.213.137:/tmp/sync_remote_db_tmp.py
sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker cp /tmp/sync_remote_db_tmp.py healthvault_bot:/tmp/sync_remote_db.py"
sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker exec healthvault_bot bash -c 'cd /tmp && python sync_remote_db.py'"
sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker cp healthvault_bot:/tmp/data /opt/healthvault/tmp_data"

echo "1.5/4 📸 Скачивание сгенерированных дампов БД и новых фотографий весов/еды..."
# Синхронизируем выгруженные логи из tmp_data и медиа из рабочей data
sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/nutrition/ ./data/nutrition/ || true
sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/supplements/ ./data/supplements/ || true
sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/weights/ ./data/weights/ || true
sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/activities/activities_remote.json ./data/activities/ || true
sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/data/media/ ./data/media/ || true

# Уборка за собой
sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "rm -rf /opt/healthvault/tmp_data /tmp/sync_remote_db_tmp.py && docker exec healthvault_bot rm -rf /tmp/data /tmp/sync_remote_db.py"

echo "1.8/4 ⚖️  Синхронизация умных весов (Zepp Life / Xiaomi SmartScale)..."
# scaleconnect v0.4.1 устарел — использует zepp.com API которое сломано (Xiaomi anti-bot)
# Новый скрипт import_zepp_api.py работает напрямую через api-mifit.zepp.com
python3 scripts/import_zepp_api.py 2>&1 || echo "   ⚠️  Zepp API: нужен свежий токен (см. scripts/import_zepp_api.py --help)"
python3 scripts/import_zepp_csv.py 2>/dev/null || true

echo "2/4 🏃 Загрузка свежего сна, стресса, HRV, Body Battery и тренировок из Garmin Connect..."
python3 scripts/garmin/download_garmin_data.py
echo "2.5/4 🏋️  Агрегация тренировок в workouts_log.json..."
python3 scripts/parse_workouts.py

echo "3/4 🌬 Загрузка данных климата в спальне из Netatmo..."
python3 scripts/import_netatmo.py

echo "4/4 📱 Загрузка экранного времени (iPhone, Mac)..."
# Требует Full Disk Access у терминала!
python3 scripts/import_activitywatch.py
python3 scripts/import_mac_screentime.py

echo "5/4 🍎 Apple Health (шаги, ходьба, АД, вес, пульс)..."
# Необязательный шаг — требует ручного экспорта Apple Health (Health → Профиль → Экспорт данных)
# Ищет export.xml в ~/Downloads/apple_health_export*/
if python3 scripts/import_apple_health.py 2>/dev/null; then
    echo "   ✅ Apple Health обновлён"
else
    echo "   ⏭  Пропущен — нет export.xml в ~/Downloads/apple_health_export*/"
    echo "      Чтобы обновить: iPhone → Health → Профиль → Экспорт данных → разархивировать zip"
fi

echo "================================================="
echo "✅ Все данные успешно скачаны и обновлены!"
echo "➡️  Данные в папках: data/nutrition, data/garmin, data/activities, data/weights, data/environment."
echo "➡️  Запусти скилл /sync для просмотра таблицы актуальности."
echo "================================================="
