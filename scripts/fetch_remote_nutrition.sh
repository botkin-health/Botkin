#!/bin/bash
SERVER="root@116.203.213.137"
PASS="SERVER_PASSWORD_REDACTED"
DIR="/opt/healthvault"

echo "Using sshpass to fetch data from $SERVER..."

# Fetch Nutrition
echo "Fetching Nutrition Log..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "docker exec healthvault_postgres psql -U healthvault -d healthvault -t -c \"COPY (SELECT json_agg(t) FROM (SELECT date::text, meal_time::text, items, totals FROM nutrition_log WHERE date >= '2026-01-01') t) TO STDOUT\"" > data/nutrition/nutrition_log_remote.json

# Check if file is empty or valid
if [ -s data/nutrition/nutrition_log_remote.json ]; then
    echo "✅ Nutrition data saved to data/nutrition/nutrition_log_remote.json"
else
    echo "⚠️  Nutrition data file is empty!"
fi

echo "Waiting 5 seconds..."
sleep 5

# Fetch Supplements
echo "Fetching Supplements Log..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "docker exec healthvault_postgres psql -U healthvault -d healthvault -t -c \"COPY (SELECT json_agg(t) FROM (SELECT date::text, supplement_name, dosage, time::text FROM supplements_log WHERE date >= '2026-01-01') t) TO STDOUT\"" > data/supplements/supplements_log_remote.json

if [ -s data/supplements/supplements_log_remote.json ]; then
    echo "✅ Supplements data saved to data/supplements/supplements_log_remote.json"
else
    echo "⚠️  Supplements data file is empty!"
fi
