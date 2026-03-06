#!/bin/bash
SERVER_IP="116.203.213.137"
SERVER_USER="root"
SERVER_PATH="/opt/healthvault"

echo "🚀 Starting Bot on Server $SERVER_IP..."
echo "Command: docker-compose up -d --build"

ssh -t ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose up -d --build && docker-compose logs -f --tail=50 bot"
