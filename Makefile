.PHONY: run run-fast stop test install clean guardrails check-secrets db-up db-down db-shell db-backup db-restore db-backup-auto db-reset

# Variables
PYTHON := ./venv/bin/python
BOT_SCRIPT := telegram-bot/bot.py

# Run the Telegram Bot (with checks!)
run: stop test
	@echo "Starting Botkin Bot..."
	$(PYTHON) $(BOT_SCRIPT)

# Run without checks (Dangerous! Use only if you know what you are doing)
run-fast: stop
	@echo "⚠️  Starting Botkin Bot (SKIPPING TESTS)..."
	$(PYTHON) $(BOT_SCRIPT)

# Stop any running bot instances
stop:
	@echo "🛑 Stopping old bot instances..."
	@pkill -f "telegram-bot/bot.py" || true

# Run tests
test:
	@echo "🛡️  Running automated tests..."
	@PYTHONPATH=. $(PYTHON) -m pytest tests

# === GUARDRAILS (AI Bug Prevention) ===

# Full validation suite (run before commit)
guardrails: check-secrets test
	@echo "✅ All guardrails passed!"

# Check for exposed secrets
check-secrets:
	@echo "🔐 Checking for exposed secrets..."
	@if git log --all --full-history -- .env .env.production 2>/dev/null | grep -q "commit"; then \
		echo "⚠️  WARNING: .env files found in git history! Rotate keys immediately."; \
		exit 1; \
	fi
	@if [ ! -f .env ]; then \
		echo "❌ ERROR: .env file missing. Copy from .env.example"; \
		exit 1; \
	fi
	@echo "✅ No secrets in git history"

# Install dependencies
install:
	@echo "Installing dependencies..."
	$(PYTHON) -m pip install -r requirements.txt

# Clean up temporary files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# === DATABASE COMMANDS (dev-контейнер; прод живёт на Hetzner, см. CLAUDE.md) ===

# Start PostgreSQL (Docker)
db-up:
	@echo "🐘 Starting PostgreSQL..."
	@docker-compose -f docker-compose.dev.yml up -d
	@echo "✅ PostgreSQL is running on localhost:5432 (db/user: healthvault)"

# Stop PostgreSQL
db-down:
	@echo "🛑 Stopping PostgreSQL..."
	@docker-compose -f docker-compose.dev.yml down

# Open PostgreSQL shell
db-shell:
	@echo "🐚 Opening PostgreSQL shell..."
	@docker exec -it healthvault_postgres_dev psql -U healthvault -d healthvault

# === DATABASE BACKUP & RESTORE ===

# Backup database to file
db-backup:
	@echo "💾 Creating database backup..."
	@mkdir -p backup
	@docker exec healthvault_postgres_dev pg_dump -U healthvault healthvault > backup/healthvault_$(shell date +%Y-%m-%d_%H%M%S).sql
	@echo "✅ Backup saved to backup/healthvault_$(shell date +%Y-%m-%d_%H%M%S).sql"
	@ls -lh backup/ | tail -5

# Restore database from latest backup
db-restore:
	@echo "⚠️  WARNING: This will overwrite current database!"
	@read -p "Enter backup filename (or 'latest'): " file && \
	if [ "$$file" = "latest" ]; then \
		latest=$$(ls -t backup/*.sql | head -1); \
		echo "Restoring from $$latest..."; \
		docker exec -i healthvault_postgres_dev psql -U healthvault -d healthvault < $$latest; \
	else \
		docker exec -i healthvault_postgres_dev psql -U healthvault -d healthvault < backup/$$file; \
	fi
	@echo "✅ Database restored"

# Auto-backup (for cron): backup and clean old backups (keep last 7 days)
db-backup-auto:
	@mkdir -p backup
	@docker exec healthvault_postgres_dev pg_dump -U healthvault healthvault > backup/healthvault_$(shell date +%Y-%m-%d).sql
	@find backup -name "healthvault_*.sql" -mtime +7 -delete
	@echo "✅ Auto-backup complete (keeping last 7 days)"

# Reset database (DANGEROUS!)
db-reset:
	@echo "⚠️  WARNING: This will delete ALL data!"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	@docker-compose -f docker-compose.dev.yml down -v
	@echo "✅ Database reset complete. Run 'make db-up' to start fresh."
