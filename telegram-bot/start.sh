#!/bin/bash
# Скрипт для запуска HealthVault Telegram Bot

cd "$(dirname "$0")"
source ../venv/bin/activate
python3 bot.py
