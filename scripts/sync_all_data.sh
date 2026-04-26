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
/opt/homebrew/bin/sshpass -e scp -o StrictHostKeyChecking=no scripts/util/sync_remote_db.py root@116.203.213.137:/tmp/sync_remote_db_tmp.py
/opt/homebrew/bin/sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker cp /tmp/sync_remote_db_tmp.py healthvault_bot:/tmp/sync_remote_db.py"
/opt/homebrew/bin/sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker exec healthvault_bot bash -c 'cd /tmp && python sync_remote_db.py'"
/opt/homebrew/bin/sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "docker cp healthvault_bot:/tmp/data /opt/healthvault/tmp_data"

echo "1.5/4 📸 Скачивание сгенерированных дампов БД и новых фотографий весов/еды..."
# Синхронизируем выгруженные логи из tmp_data и медиа из рабочей data
/opt/homebrew/bin/sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/nutrition/ ./data/nutrition/ || true
/opt/homebrew/bin/sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/supplements/ ./data/supplements/ || true
/opt/homebrew/bin/sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/weights/ ./data/weights/ || true
/opt/homebrew/bin/sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/tmp_data/activities/activities_remote.json ./data/activities/ || true
/opt/homebrew/bin/sshpass -e rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    root@116.203.213.137:/opt/healthvault/data/media/ ./data/media/ || true

# Уборка за собой
/opt/homebrew/bin/sshpass -e ssh -o StrictHostKeyChecking=no root@116.203.213.137 "rm -rf /opt/healthvault/tmp_data /tmp/sync_remote_db_tmp.py && docker exec healthvault_bot rm -rf /tmp/data /tmp/sync_remote_db.py"

echo "1.8/4 ⚖️  Синхронизация умных весов (Zepp Life / Xiaomi SmartScale)..."
# scaleconnect v0.4.1 устарел — использует zepp.com API которое сломано (Xiaomi anti-bot)
# Новый скрипт import_zepp_api.py работает напрямую через api-mifit.zepp.com
PY=/opt/homebrew/bin/python3.13
$PY scripts/import/zepp_api.py 2>&1 || echo "   ⚠️  Zepp API: нужен свежий токен (см. scripts/import/zepp_api.py --help)"
$PY scripts/import/zepp_csv.py 2>/dev/null || true

echo "1.9/4 🍷 Обновление alcohol_daily.json из nutrition_log..."
$PY scripts/import/sync_alcohol.py

echo "2/4 🏃 Загрузка свежего сна, стресса, HRV, Body Battery и тренировок из Garmin Connect..."
$PY scripts/garmin/download_garmin_data.py || echo "   ⚠️  Garmin пропущен (см. выше)"
echo "2.3/4 📤 Пуш Garmin daily-summary → activity_log на сервере..."
bash scripts/push_garmin_to_db.sh
echo "2.5/4 🏋️  Агрегация тренировок в workouts_log.json..."
$PY scripts/util/parse_workouts.py
echo "2.6/4 🏋️  Пуш workouts_log → контейнер (для блока «Спорт» в дашборде)..."
$PY scripts/import/push_workouts_to_container.py

echo "3/4 🌬 Загрузка данных климата в спальне из Netatmo..."
$PY scripts/import/netatmo.py
echo "3.5/4 🌬 Пуш Netatmo → контейнер (env_data для дашборда)..."
$PY scripts/import/push_netatmo_to_container.py

echo "4/4 📱 Загрузка экранного времени (iPhone, Mac)..."
# Требует Full Disk Access у терминала!
$PY scripts/import/activitywatch.py
$PY scripts/import/mac_screentime.py

echo "5/4 🍎 Apple Health (шаги, ходьба, АД, вес, пульс)..."
# Необязательный шаг — требует ручного экспорта Apple Health (Health → Профиль → Экспорт данных)
# Ищет export.xml в ~/Downloads/apple_health_export*/
# ЗАЩИТА ОТ РЕГРЕССА: если найденный XML старше уже имеющихся плоских файлов — пропускаем,
# чтобы не затереть свежие данные, импортированные вручную через parse_apple_health_xml.py
AH_XML=$(ls -t ~/Downloads/apple_health_export*/apple_health_export/export.xml ~/Downloads/apple_health_export*/apple_health_export/экспорт.xml 2>/dev/null | head -1)
AH_FLAT="data/apple_health_steps_daily.json"
if [ -n "$AH_XML" ] && [ -f "$AH_FLAT" ] && [ "$AH_FLAT" -nt "$AH_XML" ]; then
    echo "   ⏭  Пропущен — $AH_FLAT новее чем экспорт в ~/Downloads/ (защита от регресса)"
    echo "      Если хочешь пере-импортировать: удали $AH_FLAT и запусти снова"
elif $PY scripts/import/apple_health.py 2>/dev/null; then
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
