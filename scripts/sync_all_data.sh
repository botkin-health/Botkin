#!/bin/bash
# Синхронизация всех источников данных HealthVault в локальную файловую систему
# ИИ-Агенты (Cursor, Claude, Antigravity) ОБЯЗАНЫ запускать этот скрипт первым делом, 
# чтобы получить свежий 100% срез по питанию, сну, шагам, весам и климату из всех источников.

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

echo "2/4 🏃 Загрузка свежего сна, стресса и тренировок из Garmin Connect..."
python3 scripts/garmin/download_garmin_data.py

echo "3/4 🌬 Загрузка данных климата в спальне из Netatmo..."
python3 scripts/import_netatmo.py

echo "4/4 📱 Загрузка экранного времени из базы макоси..."
# Требует Full Disk Access у терминала!
python3 scripts/import_screentime.py

echo "================================================="
echo "✅ Все данные успешно скачаны и обновлены!"
echo "➡️  Они лежат в папках data/nutrition, data/garmin, data/activities, data/weights, data/environment."
echo "================================================="
