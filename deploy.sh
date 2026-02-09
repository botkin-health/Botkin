#!/bin/bash
set -e  # Exit on error

# Настройки сервера
SERVER_IP="146.103.111.109"
SERVER_USER="root"
SERVER_PATH="/root/healthvault"
SERVER_PASSWORD="SERVER_PASSWORD_REDACTED"

echo "==================================="
echo "🚀 HealthVault Deployment Script"
echo "==================================="
echo "🎯 Target: $SERVER_USER@$SERVER_IP:$SERVER_PATH"
echo ""

# Parse command line arguments
REBUILD_MODE="normal"  # Options: normal, force, skip
NO_CACHE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --force-rebuild)
            REBUILD_MODE="force"
            NO_CACHE="--no-cache"
            shift
            ;;
        --skip-rebuild)
            REBUILD_MODE="skip"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--force-rebuild|--skip-rebuild]"
            exit 1
            ;;
    esac
done

# Проверка что есть все нужные файлы
echo "🔍 Checking required files..."

if [ ! -f "Dockerfile" ]; then
    echo "❌ Dockerfile not found!"
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt not found!"
    exit 1
fi

echo "✅ All required files found"
echo ""

# 1. Upload code to server
echo "📤 Step 1/4: Uploading code to server..."
sshpass -p "$SERVER_PASSWORD" rsync -avz \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'logs/*' \
    --exclude 'data/garmin/*' \
    --exclude '.env.local' \
    ./ ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/

echo "✅ Code uploaded successfully"
echo ""

# 2. Rebuild Docker image (CRITICAL for code changes!)
if [ "$REBUILD_MODE" = "skip" ]; then
    echo "⏭️  Step 2/4: Skipping Docker rebuild (--skip-rebuild flag)"
else
    if [ "$REBUILD_MODE" = "force" ]; then
        echo "🔨 Step 2/4: Rebuilding Docker image (FORCE MODE - no cache)..."
    else
        echo "🔨 Step 2/4: Rebuilding Docker image..."
    fi
    
    sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
        "cd ${SERVER_PATH} && docker-compose build $NO_CACHE bot"
    
    echo "✅ Docker image rebuilt successfully"
fi
echo ""

# 3. Restart containers with new image
echo "♻️  Step 3/4: Restarting containers..."
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "cd ${SERVER_PATH} && docker-compose up -d"

echo "✅ Containers restarted"
echo ""

# 4. Verify deployment
echo "🏥 Step 4/4: Verifying deployment..."
sleep 3

# Check container status
echo ""
echo "Container status:"
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "docker-compose ps"

echo ""
echo "Recent logs:"
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "docker logs --tail 30 healthvault_bot"

# Check file date in container to verify rebuild
echo ""
echo "🔍 Verifying code update in container..."
FILE_DATE=$(sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "docker exec healthvault_bot stat -c %y /app/telegram-bot/handlers/photo.py | cut -d' ' -f1")

echo "📅 Code file date in container: $FILE_DATE"
TODAY=$(date +%Y-%m-%d)

if [ "$FILE_DATE" = "$TODAY" ]; then
    echo "✅ Code is up-to-date (file from today)"
else
    echo "⚠️  WARNING: Code might be outdated (file from $FILE_DATE, today is $TODAY)"
    echo "   This might mean Docker rebuild failed or was skipped"
fi

echo ""
echo "==================================="
echo "✅ Deployment complete!"
echo "==================================="
echo ""
echo "📊 Monitor logs: ssh ${SERVER_USER}@${SERVER_IP} 'docker logs -f healthvault_bot'"
echo "🔧 Check status: ssh ${SERVER_USER}@${SERVER_IP} 'docker-compose ps'"
echo ""


# Копируем data/ но исключаем большие XML файлы Apple Health
rsync -av --exclude='apple-health/export*.xml' data/ $DEPLOY_DIR/data/

echo "📤 Uploading to server..."
echo "⚠️  You will be prompted for server password"
echo ""

# Создаем директорию на сервере
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${SERVER_PATH}"

# Загружаем файлы
rsync -avz --progress $DEPLOY_DIR/ ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/

echo ""
echo "✅ Files uploaded successfully!"
echo ""
echo "=== Next Steps ==="
echo "Run the following command to start the bot on server:"
echo ""
echo "  ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && docker-compose up -d'"
echo ""
echo "Or use auto_deploy.exp for automated deployment"

# Cleanup
rm -rf $DEPLOY_DIR
