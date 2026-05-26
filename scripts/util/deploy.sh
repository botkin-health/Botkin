#!/bin/bash
# Deploy HealthVault bot to production server.
# Usage: ./scripts/util/deploy.sh [--full-rebuild]
#
# Default (fast): rsync source → docker cp changed files → restart bot
# --full-rebuild: rsync source → docker compose build → force-recreate
#
# The server has no git. Source is synced via rsync, then deployed to
# the running container (fast) or via a full image rebuild (slow, ~2 min).

set -euo pipefail

SERVER="root@116.203.213.137"
SSH="ssh -o StrictHostKeyChecking=no $SERVER"
SCP="scp -o StrictHostKeyChecking=no"
SERVER_DIR="/opt/healthvault"
CONTAINER="healthvault_bot"

FULL_REBUILD=false
if [[ "${1:-}" == "--full-rebuild" ]]; then
  FULL_REBUILD=true
fi

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
echo "🚀 Deploying HealthVault from: $PROJECT_DIR"

# ── Step 1: rsync source code to server ───────────────────────────────────
echo ""
echo "📦 Syncing source code to server..."
rsync -az --delete -e "ssh -o StrictHostKeyChecking=no" \
  --exclude='data/' \
  --exclude='venv/' \
  --exclude='venv_mcp/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='logs/' \
  --exclude='.env' \
  --exclude='.env.production' \
  --exclude='*.egg-info/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  "$PROJECT_DIR/" \
  "$SERVER:$SERVER_DIR/"
echo "✅ Source synced"

# ── Step 2a: Full rebuild (slow, use after adding dependencies) ────────────
if $FULL_REBUILD; then
  echo ""
  echo "🔨 Full rebuild requested — building Docker image..."
  $SSH "cd $SERVER_DIR && docker compose build bot 2>&1 | tail -5"
  echo ""
  echo "🔄 Recreating container..."
  $SSH "cd $SERVER_DIR && docker compose up -d --force-recreate bot 2>&1 | grep -v 'warning\|Warning'"
  echo "✅ Container recreated with new image"

# ── Step 2b: Fast deploy — copy files into running container ──────────────
else
  echo ""
  echo "⚡ Fast deploy — copying changed source files into container..."
  $SSH "
    # Core source directories
    docker cp $SERVER_DIR/config/. $CONTAINER:/app/config/
    docker cp $SERVER_DIR/core/. $CONTAINER:/app/core/
    docker cp $SERVER_DIR/database/. $CONTAINER:/app/database/
    docker cp $SERVER_DIR/domain/. $CONTAINER:/app/domain/
    docker cp $SERVER_DIR/helpers/. $CONTAINER:/app/helpers/
    docker cp $SERVER_DIR/services/. $CONTAINER:/app/services/
    docker cp $SERVER_DIR/telegram-bot/. $CONTAINER:/app/telegram-bot/
    echo '✅ Files copied to container'

    # Restart bot process
    docker restart $CONTAINER
    echo '🔄 Container restarted'
  "
fi

# ── Step 3: Wait for health check ─────────────────────────────────────────
echo ""
echo "⏳ Waiting for bot to start..."
sleep 6
STATUS=$($SSH "docker inspect --format='{{.State.Status}}' $CONTAINER")
HEALTH=$($SSH "docker inspect --format='{{.State.Health.Status}}' $CONTAINER" 2>/dev/null || echo "unknown")
echo "Container: $STATUS (health: $HEALTH)"

# ── Step 4: Smoke test ────────────────────────────────────────────────────
echo ""
echo "🧪 Smoke test — new user registration..."
$SSH "docker exec $CONTAINER python3 -c \"
import sys; sys.path.insert(0, '/app')
from database import SessionLocal
from database.models import User, UserSettings
from database.crud import ensure_user_exists, get_user_settings

db = SessionLocal()
TEST_ID = 100000001
try:
    db.query(UserSettings).filter_by(user_id=TEST_ID).delete()
    db.query(User).filter_by(telegram_id=TEST_ID).delete()
    db.commit()
    user = ensure_user_exists(db, telegram_id=TEST_ID, username='deploy_smoke', first_name='DeployTest')
    settings = get_user_settings(db, TEST_ID)
    assert user.is_active, 'User not active'
    assert settings is not None, 'UserSettings not created'
    assert settings.calorie_goal_pct == -15, f'Wrong goal_pct: {settings.calorie_goal_pct}'
    print('✅ Smoke test passed: user registration + UserSettings OK')
except Exception as e:
    print(f'❌ Smoke test FAILED: {e}')
finally:
    db.close()
\""

echo ""
echo "🎉 Deploy complete!"
