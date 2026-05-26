#!/bin/bash
SERVER="root@116.203.213.137"
DIR="/opt/healthvault"

echo "Checking remote containers..."
ssh -o StrictHostKeyChecking=no $SERVER "cd $DIR && docker-compose ps && echo '---' && docker ps"
