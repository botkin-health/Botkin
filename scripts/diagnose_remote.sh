#!/bin/bash
SERVER="root@116.203.213.137"
PASS="SERVER_PASSWORD_REDACTED"
DIR="/opt/healthvault"

echo "Checking remote containers..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "cd $DIR && docker-compose ps && echo '---' && docker ps"
