#!/bin/bash
SERVER="root@116.203.213.137"
PASS="W749a#j%37z8_138UBYA"
DIR="/opt/healthvault"

echo "Checking remote containers..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no $SERVER "cd $DIR && docker-compose ps && echo '---' && docker ps"
