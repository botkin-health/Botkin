#!/bin/bash
SERVER="root@146.103.111.109"
PASS="SERVER_PASSWORD_REDACTED"
DIR="/root/healthvault"

echo "Checking remote containers..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "cd $DIR && docker-compose ps && echo '---' && docker ps"
