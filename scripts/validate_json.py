#!/usr/bin/env python3
"""Validate JSON schemas for HealthVault data files."""
import json
import sys
from pathlib import Path

# Проверяем только существующие JSON (питание в БД, локальные файлы опциональны)
FILES_TO_CHECK = [
    "data/nutrition/nutrition_log_remote.json",
]

def main():
    errors = []
    for filepath in FILES_TO_CHECK:
        if not Path(filepath).exists():
            continue
        try:
            with open(filepath) as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"{filepath}: {e}")
    if errors:
        print("❌ JSON validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    print("✅ All JSON files valid")

if __name__ == "__main__":
    main()
