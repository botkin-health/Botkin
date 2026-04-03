#!/bin/bash
set -e  # Exit on error

# Настройки сервера
SERVER_IP="116.203.213.137"
SERVER_USER="root"
SERVER_PATH="/opt/healthvault"
SERVER_PASSWORD="SERVER_PASSWORD_REDACTED"

echo "==================================="
echo "🚀 HealthVault Deployment Script"
echo "==================================="
echo "🎯 Target: $SERVER_USER@$SERVER_IP:$SERVER_PATH"
echo ""

# Parse command line arguments
REBUILD_MODE="normal"  # Options: normal, force, skip
NO_CACHE=""
SKIP_LLM_TESTS=false

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
        --skip-llm-tests)
            SKIP_LLM_TESTS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--force-rebuild|--skip-rebuild|--skip-llm-tests]"
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
export PATH="/opt/homebrew/bin:$PATH"
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
        "cd ${SERVER_PATH} && (command -v docker-compose >/dev/null 2>&1 && docker-compose build $NO_CACHE bot || docker compose build $NO_CACHE bot)"
    
    echo "✅ Docker image rebuilt successfully"
fi
echo ""

# 3. Restart containers with new image
echo "♻️  Step 3/4: Restarting containers..."
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "cd ${SERVER_PATH} && (command -v docker-compose >/dev/null 2>&1 && docker-compose up -d || docker compose up -d)"

echo "✅ Containers restarted"
echo ""

# 4. Verify deployment
echo "🏥 Step 4/4: Verifying deployment..."
sleep 3

# Check container status
echo ""
echo "Container status:"
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
    "cd ${SERVER_PATH} && (command -v docker-compose >/dev/null 2>&1 && docker-compose ps || docker compose ps)"

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

# 5. LLM Prompt E2E Tests (проверяем что промпт работает корректно после изменений)
if [ "$SKIP_LLM_TESTS" = true ]; then
    echo "⏭️  Step 5/5: LLM prompt tests skipped (--skip-llm-tests)"
else
    echo "🧪 Step 5/5: Running LLM prompt E2E tests..."
    echo "   (Проверяем что GPT отвечает корректно — займёт ~30-60 секунд)"
    echo ""

    # Ждём пока контейнер полностью поднимется (healthcheck)
    for i in {1..12}; do
        STATUS=$(sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
            "docker inspect --format='{{.State.Health.Status}}' healthvault_bot 2>/dev/null || echo 'unknown'")
        if [ "$STATUS" = "healthy" ]; then
            break
        fi
        echo "   ⏳ Ждём healthcheck... ($i/12)"
        sleep 5
    done

    # Запускаем тесты внутри боевого контейнера
    LLM_TEST_OUTPUT=$(sshpass -p "$SERVER_PASSWORD" ssh ${SERVER_USER}@${SERVER_IP} \
        "docker exec healthvault_bot python /app/scripts/test_llm_prompt.py 2>&1")
    LLM_TEST_EXIT=$?

    echo "$LLM_TEST_OUTPUT"
    echo ""

    if [ $LLM_TEST_EXIT -eq 0 ]; then
        echo "✅ LLM prompt tests PASSED — промпт работает корректно"
    else
        echo "❌ LLM prompt tests FAILED — промпт может работать некорректно!"
        echo ""
        echo "   Возможные причины:"
        echo "   1. Изменение промпта сломало существующее поведение → откатить изменения"
        echo "   2. OpenAI API временно недоступен / нет баланса → повторить через пару минут"
        echo "   3. Новый тест-кейс некорректно написан → проверить scripts/test_llm_prompt.py"
        echo ""
        echo "   Повторить тесты: ssh ${SERVER_USER}@${SERVER_IP} 'docker exec healthvault_bot python /app/scripts/test_llm_prompt.py'"
        echo ""
        echo "   ⚠️  Деплой завершён, бот работает. Тесты — предупреждение, не блокировка."
    fi
fi

echo ""
