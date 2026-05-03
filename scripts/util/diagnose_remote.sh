#!/bin/bash
SERVER="root@116.203.213.137"
PASS="${SERVER_PASSWORD:-$(grep '^SERVER_PASSWORD=' "$(dirname "$0")/../../.env" 2>/dev/null | cut -d= -f2)}"
if [ -z "$PASS" ]; then echo "❌ SERVER_PASSWORD not set in .env" && exit 1; fi
DIR="/opt/healthvault"

echo "Checking remote containers..."
/opt/homebrew/bin/sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "cd $DIR && docker-compose ps && echo '---' && docker ps"
