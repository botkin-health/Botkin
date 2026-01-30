#!/bin/bash

# Database migration script
# Exports local PostgreSQL data and uploads to production server

echo "=== HealthVault Database Migration ==="
echo ""

# Configuration
LOCAL_CONTAINER="healthvault_postgres_dev"
LOCAL_DB="healthvault"
LOCAL_USER="healthvault"
DUMP_FILE="healthvault_backup_$(date +%Y%m%d_%H%M%S).sql"
SERVER_IP="95.142.45.135"
SERVER_USER="root"
SERVER_PATH="/root/healthvault"

# Step 1: Check local PostgreSQL is running
echo "📊 Step 1/5: Checking local PostgreSQL..."
if ! docker ps | grep -q $LOCAL_CONTAINER; then
    echo "❌ Local PostgreSQL container is not running!"
    echo "Start it with: docker start $LOCAL_CONTAINER"
    exit 1
fi
echo "✅ Local PostgreSQL is running"
echo ""

# Step 2: Create database dump
echo "💾 Step 2/5: Creating database dump..."
docker exec $LOCAL_CONTAINER pg_dump -U $LOCAL_USER -d $LOCAL_DB > $DUMP_FILE

if [ ! -f "$DUMP_FILE" ]; then
    echo "❌ Failed to create dump file!"
    exit 1
fi

DUMP_SIZE=$(du -h $DUMP_FILE | cut -f1)
echo "✅ Dump created: $DUMP_FILE ($DUMP_SIZE)"
echo ""

# Step 3: Upload dump to server
echo "📤 Step 3/5: Uploading dump to server..."
echo "⚠️  You will be prompted for server password"
scp $DUMP_FILE ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/

echo "✅ Dump uploaded"
echo ""

# Step 4: Restore on server
echo "🔄 Step 4/5: Restoring database on server..."
echo "⚠️  You will be prompted for server password again"

ssh ${SERVER_USER}@${SERVER_IP} << EOF
cd ${SERVER_PATH}
echo "Waiting for PostgreSQL to be ready..."
docker-compose exec -T postgres pg_isready -U healthvault || sleep 5
echo "Restoring database..."
docker-compose exec -T postgres psql -U healthvault -d healthvault < $DUMP_FILE
echo "✅ Database restored"
EOF

echo ""

# Step 5: Verify migration
echo "✅ Step 5/5: Verifying migration..."
echo "Checking record counts..."

# Get local counts
echo "Local database:"
docker exec $LOCAL_CONTAINER psql -U $LOCAL_USER -d $LOCAL_DB -c "
SELECT 
    'nutrition_log' as table_name, COUNT(*) as count FROM nutrition_log WHERE user_id=895655
UNION ALL
SELECT 'supplements_log', COUNT(*) FROM supplements_log WHERE user_id=895655
UNION ALL  
SELECT 'activity_log', COUNT(*) FROM activity_log WHERE user_id=895655
UNION ALL
SELECT 'weights', COUNT(*) FROM weights WHERE user_id=895655;
"

echo ""
echo "=== Migration Summary ==="
echo "✅ Dump file: $DUMP_FILE (saved locally)"
echo "✅ Uploaded to: ${SERVER_IP}:${SERVER_PATH}/"
echo "✅ Restored to production database"
echo ""
echo "To verify on server, run:"
echo "  ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && docker-compose exec postgres psql -U healthvault -d healthvault -c \"SELECT COUNT(*) FROM nutrition_log;\"'"
echo ""
echo "⚠️  Keep the dump file ${DUMP_FILE} as backup!"
