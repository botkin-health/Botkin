#!/bin/bash
SERVER_IP="116.203.213.137"
SERVER_USER="root"

echo "🔍 Connecting to $SERVER_IP..."

ssh -o ConnectTimeout=10 ${SERVER_USER}@${SERVER_IP} "
    echo '=== 1. DOCKER CONTAINERS ==='
    docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}'
    
    echo -e '\n=== 2. DOCKER NETWORKS ==='
    docker network ls
    
    echo -e '\n=== 3. BOT LOGS (Last 20 lines) ==='
    docker logs --tail 20 healthvault_bot 2>&1
    
    echo -e '\n=== 4. POSTGRES LOGS (Last 20 lines) ==='
    docker logs --tail 20 healthvault_postgres 2>&1
    
    echo -e '\n=== 5. ENV VARS CHECK (Bot) ==='
    docker exec healthvault_bot env | grep DATABASE_URL || echo 'Bot container not running or exec failed'
    
    echo -e '\n=== 6. PING CHECK (Bot -> Postgres) ==='
    docker exec healthvault_bot ping -c 1 postgres || echo 'Ping failed'
"
