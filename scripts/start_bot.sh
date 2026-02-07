#!/bin/bash
SERVER_IP="146.103.111.109"
SERVER_USER="root"
SERVER_PATH="/root/healthvault"

echo "🚀 Starting Bot on Server $SERVER_IP..."
echo "Command: docker-compose up -d --build"

ssh -t ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose up -d --build && docker-compose logs -f --tail=50 bot"
