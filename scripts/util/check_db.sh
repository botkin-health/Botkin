#!/bin/bash
# Quick test script - проверяет последние записи в БД

echo "📊 Последние записи в PostgreSQL:"
echo ""

echo "🍽️ Nutrition (последние 3):"
docker exec healthvault_postgres_dev psql -U healthvault -d healthvault -c "
SELECT 
    date,
    meal_time::text as time,
    meal_name,
    (totals->>'calories')::text as cal,
    (totals->>'protein')::text as prot
FROM nutrition_log 
WHERE user_id = 895655 
ORDER BY date DESC, meal_time DESC 
LIMIT 3;
"

echo ""
echo "💊 Supplements (сегодня):"
docker exec healthvault_postgres_dev psql -U healthvault -d healthvault -c "
SELECT 
    time::text,
    supplement_name
FROM supplements_log 
WHERE user_id = 895655 AND date = CURRENT_DATE
ORDER BY time DESC;
"

echo ""
echo "⚖️ Weights (последние 3):"
docker exec healthvault_postgres_dev psql -U healthvault -d healthvault -c "
SELECT 
    measured_at::date as date,
    weight,
    body_fat
FROM weights 
WHERE user_id = 895655 
ORDER BY measured_at DESC 
LIMIT 3;
"
