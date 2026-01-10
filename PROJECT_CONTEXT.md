# HealthVault Project Context

## Overview
**HealthVault** is a personal health tracking system integrated with Telegram. It aggregates data from Apple Health, Samsung Health/Zepp, Garmin, SleepCycle, and manual nutrition logs.

## Architecture
- **Interface**: Telegram Bot (`telegram-bot/`, `aiogram` 3.x)
- **Data Storage**:
    - **Local JSON**: `data/nutrition/nutrition_log.json`, `knowledge_base.json`
    - **Raw Exports**: `data/apple-health/`, `data/garmin/`
- **Processing**: Python scripts in `scripts/` for parsing exports and OCR.

## Key Directories
- `telegram-bot/`: Main bot logic.
    - `handlers/`: Command and message handlers (`text.py`, `photo.py`).
    - `services/`: Business logic (Nutrition, OCR, Stats).
- `scripts/`: Standalone ETL scripts.
- `data/`: **PRIVATE** user data (excluded from git except for structure).

## Development Rules
1.  **Safety**: NEVER commit `.env` or API keys. Use `dotenv`.
2.  **Privacy**: Do not output raw PII or medical data to unknown channels.
3.  **Logs**: Write to `logs/`, do not spam stdout.
4.  **Dependencies**: Managed in root `requirements.txt`.
5.  **Bot Updates**: Handled via `aiogram` routers.

## Common Tasks
- **Run Bot**: `python3 telegram-bot/bot.py`
- **Analyze Food**: Bot accepts text or photos (via Gemini/OpenAI).
- **Sync Data**: Run `scripts/apple-health/run_update.py`.
