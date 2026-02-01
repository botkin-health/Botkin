#!/usr/bin/env python3
"""Validate JSON schemas for HealthVault data files."""
import json
import sys
from pathlib import Path

FILES_TO_CHECK = [
    "data/nutrition/nutrition_log.json",
]

def main():
    errors = []
    for filepath in FILES_TO_CHECK:
        try:
            with open(filepath) as f:
                json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            errors.append(f"{filepath}: {e}")
    
    if errors:
        print("❌ JSON validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    
    print("✅ All JSON files valid")

if __name__ == "__main__":
    main()
