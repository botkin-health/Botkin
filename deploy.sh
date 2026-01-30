#!/bin/bash

# Настройки сервера
SERVER_IP="95.142.45.135"
SERVER_USER="root"
SERVER_PATH="/root/healthvault"

echo "=== HealthVault Deployment Script ==="
echo "🎯 Target: $SERVER_USER@$SERVER_IP:$SERVER_PATH"
echo ""

# Проверка что есть все нужные файлы
if [ ! -f "docker-compose.prod.yml" ]; then
    echo "❌ docker-compose.prod.yml not found!"
    exit 1
fi

if [ ! -f "Dockerfile" ]; then
    echo "❌ Dockerfile not found!"
    exit 1
fi

if [ ! -f ".env.production" ]; then
    echo "⚠️  .env.production not found! Copy from .env.production.example and edit!"
    exit 1
fi

echo "✅ All required files found"
echo ""

# Создание временной папки для деплоя
DEPLOY_DIR="./deploy_temp"
rm -rf $DEPLOY_DIR
mkdir -p $DEPLOY_DIR

echo "📦 Preparing deployment package..."

# Копирование необходимых файлов
cp docker-compose.prod.yml $DEPLOY_DIR/docker-compose.yml
cp Dockerfile $DEPLOY_DIR/
cp .env.production $DEPLOY_DIR/.env
cp requirements.txt $DEPLOY_DIR/
cp -r telegram-bot $DEPLOY_DIR/
cp -r config $DEPLOY_DIR/
cp -r core $DEPLOY_DIR/
cp -r services $DEPLOY_DIR/
cp -r database $DEPLOY_DIR/
cp -r helpers $DEPLOY_DIR/
cp -r domain $DEPLOY_DIR/

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
