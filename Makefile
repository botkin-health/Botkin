.PHONY: run install backup clean

# Variables
PYTHON := ./venv/bin/python
BOT_SCRIPT := telegram-bot/bot.py
BACKUP_SCRIPT := scripts/create_backup.sh

# Run the Telegram Bot
run:
	@echo "Starting HealthVault Bot..."
	$(PYTHON) $(BOT_SCRIPT)

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
