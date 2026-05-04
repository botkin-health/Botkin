# Sprint 1a — Deploy Notes

## What was done

Sprint 1a delivers the Telegram webhook integration for `@HealthVault_bot`:

- **`telegram-bot/webhook/apple_health.py`** — added `POST /telegram/webhook` endpoint and
  `set_telegram_dispatcher(bot, dp)` helper so the FastAPI server can feed Telegram updates
  to the aiogram dispatcher.
- **`telegram-bot/bot.py`** — removed `delete_webhook` call on startup; switched from polling
  mode to webhook mode (FastAPI server is the only entry point for Telegram updates now).

## Bot & webhook info

| Parameter | Value |
|-----------|-------|
| Bot username | `@HealthVault_bot` |
| Bot token env var | `TELEGRAM_BOT_TOKEN` |
| Webhook URL | `https://health.orangegate.cc/telegram/webhook` |
| Server | `root@116.203.213.137` |
| Container | `healthvault_bot` |
| Internal port | 8081 (mapped from host 8081) |

Webhook registration command (one-off, already done):
```bash
BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2)
curl -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=https://health.orangegate.cc/telegram/webhook"
```

Verify:
```bash
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

## Endpoints on health.orangegate.cc

| Path | Method | Purpose |
|------|--------|---------|
| `/telegram/webhook` | POST | Telegram bot updates (this sprint) |
| `/apple_health` | POST | Apple Health v1 (legacy Shortcut) |
| `/apple_health_v2` | POST | Apple Health v2 (Health Auto Export app) |
| `/nutrition` | POST/GET | Nutrition API |
| `/supplements` | POST/GET | Supplements API |
| `/webapp/` | GET | Day dashboard web app |
| `/health` | GET | Liveness probe |

## How to deploy after code changes

The bot code is baked into the Docker image. After pushing to git, deploy to server:

```bash
# 1. Push local changes
git push origin main

# 2. Pull on server, rebuild image, restart
ssh root@116.203.213.137 "cd /opt/healthvault && git pull && docker-compose build bot && docker-compose up -d bot"

# 3. Verify container is up
ssh root@116.203.213.137 "docker ps | grep healthvault_bot"
```

Or use the automated script:
```bash
./deploy.sh
```

## How to check logs

```bash
# Last 50 lines
ssh root@116.203.213.137 "docker logs --tail 50 healthvault_bot"

# Stream in real time
ssh root@116.203.213.137 "docker logs -f healthvault_bot"

# Errors only
ssh root@116.203.213.137 "docker logs healthvault_bot 2>&1 | grep ERROR"
```

## How to verify webhook is live

```bash
BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2)

# Check registration
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool

# Test endpoint directly
curl -s https://health.orangegate.cc/telegram/webhook \
  -X POST -H "Content-Type: application/json" \
  -d '{"update_id":1,"message":{"message_id":1,"from":{"id":0,"is_bot":false,"first_name":"test"},"chat":{"id":0,"type":"private"},"date":1700000000,"text":"test"}}'
```

## Architecture notes

```
iPhone / Telegram
      |
      | HTTPS POST
      v
Cloudflare (SSL termination)
      |
      | HTTP
      v
nginx on server (port 80)
  health.orangegate.cc → 127.0.0.1:8081
      |
      v
Docker container: healthvault_bot
  FastAPI / uvicorn on port 8081
  ├── POST /telegram/webhook  → aiogram dp.feed_update()
  ├── POST /apple_health_v2   → Health Auto Export
  └── GET  /webapp/           → day dashboard
```

## Known issues / next steps

- The server has no git remote configured (`master` branch with no commits) — code is synced
  via `rsync` in `deploy.sh`, not via `git pull`. After Sprint 1a, consider migrating to
  a proper git-based deploy.
- Webhook secret token not yet set (Telegram supports `secret_token` header for extra security).
  Add in Sprint 1b.
