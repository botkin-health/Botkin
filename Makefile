.PHONY: run install backup clean test check-types

# Variables
PYTHON := ./venv/bin/python
BOT_SCRIPT := telegram-bot/bot.py
BACKUP_SCRIPT := scripts/create_backup.sh

# Run the Telegram Bot (with checks!)
run: stop test check-types
	@echo "Starting HealthVault Bot..."
	$(PYTHON) $(BOT_SCRIPT)

# Run without checks (Dangerous! Use only if you know what you are doing)
run-fast: stop
	@echo "⚠️  Starting HealthVault Bot (SKIPPING TESTS)..."
	$(PYTHON) $(BOT_SCRIPT)

# Stop any running bot instances
stop:
	@echo "🛑 Stopping old bot instances..."
	@pkill -f "telegram-bot/bot.py" || true

# Run tests
test:
	@echo "🛡️  Running automated tests..."
	@PYTHONPATH=. $(PYTHON) -m pytest tests

# Check types
check-types:
	@echo "🧐 Checking types with mypy..."
	@$(PYTHON) -m mypy core/supplements.py

# === GUARDRAILS (AI Bug Prevention) ===

# Full validation suite (run before commit)
guardrails: check-secrets check-json-schema test check-types
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

# Validate JSON schemas (weights, nutrition logs)
check-json-schema:
	@echo "📋 Validating JSON data schemas..."
	@$(PYTHON) scripts/validate_json.py

# Install dependencies
install:
	@echo "Installing dependencies..."
	$(PYTHON) -m pip install -r requirements.txt

# Create a backup
backup:
	@echo "Creating backup..."
	@chmod +x $(BACKUP_SCRIPT)
	./$(BACKUP_SCRIPT)

# Clean up temporary files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# === DATABASE COMMANDS ===

# Start PostgreSQL (Docker)
db-up:
	@echo "🐘 Starting PostgreSQL..."
	@docker-compose -f docker-compose.dev.yml up -d
	@echo "✅ PostgreSQL is running on localhost:5432"
	@echo "   Database: healthvault"
	@echo "   User: healthvault"
	@echo "   Password: dev_password_123"

# Stop PostgreSQL
db-down:
	@echo "🛑 Stopping PostgreSQL..."
	@docker-compose -f docker-compose.dev.yml down

# Migrate data from JSON to PostgreSQL
db-migrate:
	@echo "📦 Migrating data to PostgreSQL..."
	@$(PYTHON) scripts/migrate_to_postgres.py

# Backfill Garmin data (last 30 days)
# Forces connection to localhost:5432 with dev credentials
db-backfill-garmin:
	@echo "🔄 Backfilling Garmin data (last 30 days)..."
	@DATABASE_URL=postgresql://healthvault:dev_password_123@localhost:5432/healthvault $(PYTHON) scripts/backfill_garmin.py 30

# Check today's data in DB
db-check-today:
	@echo "🔎 Checking today's data in DB..."
	@DATABASE_URL=postgresql://healthvault:dev_password_123@localhost:5432/healthvault $(PYTHON) scripts/check_today_data.py

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
