#!/usr/bin/env python3
"""
Migration script: JSON/CSV files → PostgreSQL
Migrates HealthVault data to structured database.

Usage:
    python scripts/migrate_to_postgres_v2.py [--dry-run] [--limit N]
"""

import argparse
import json
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import psycopg2
from psycopg2.extras import execute_values

# Configuration
DATA_DIR = Path("data")
WEIGHTS_DIR = DATA_DIR / "weights"
NUTRITION_FILE = DATA_DIR / "nutrition" / "nutrition_log.json"
BP_FILE = DATA_DIR / "apple-health" / "parsed" / "blood_pressure_manual.csv"

# Default user (single-user mode)
DEFAULT_USER_ID = 895655  # Your Telegram ID


class DatabaseMigrator:
    """Handles migration of JSON/CSV data to PostgreSQL."""
    
    def __init__(self, conn_string: str, dry_run: bool = False):
        self.conn_string = conn_string
        self.dry_run = dry_run
        self.stats = {
            "weights": 0,
            "bp": 0,
            "nutrition_entries": 0,
            "nutrition_items": 0,
            "errors": []
        }
    
    def migrate(self, limit: int = None):
        """Run full migration."""
        print("🚀 Starting migration to PostgreSQL...")
        
        if self.dry_run:
            print("⚠️  DRY RUN MODE - No data will be written")
        
        with psycopg2.connect(self.conn_string) as conn:
            # Ensure user exists
            self._ensure_user(conn)
            
            # Migrate weights
            self._migrate_weights(conn, limit)
            
            # Migrate blood pressure
            self._migrate_blood_pressure(conn, limit)
            
            # Migrate nutrition
            self._migrate_nutrition(conn, limit)
            
            if not self.dry_run:
                conn.commit()
        
        self._print_stats()
    
    def _ensure_user(self, conn):
        """Ensure default user exists in database."""
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (telegram_id, first_name, is_active)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING
            """, (DEFAULT_USER_ID, "Alexander", True))
            print(f"✅ User {DEFAULT_USER_ID} ensured")
    
    def _migrate_weights(self, conn, limit: int = None):
        """Migrate weight logs from JSON files."""
        print("\n📊 Migrating weight logs...")
        
        weight_files = sorted(WEIGHTS_DIR.glob("*.json"))
        if limit:
            weight_files = weight_files[:limit]
        
        for filepath in weight_files:
            try:
                with open(filepath) as f:
                    data = json.load(f)
                
                for entry in data:
                    # Skip if no weight data
                    if "weight" not in entry:
                        continue
                    
                    # Parse timestamp (support both formats)
                    try:
                        measured_at = datetime.strptime(
                            entry["date"], "%Y-%m-%d %H:%M"
                        )
                    except ValueError:
                        # Fallback: date only (assume 00:00)
                        measured_at = datetime.strptime(
                            entry["date"], "%Y-%m-%d"
                        )
                    
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO weight_logs (
                                user_id, measured_at, weight, bmi, body_fat,
                                visceral_fat, water, muscle, bone_mass,
                                protein_percentage, bmr, body_score, body_type, source
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (user_id, measured_at) DO NOTHING
                        """, (
                            DEFAULT_USER_ID, measured_at,
                            entry.get("weight"), entry.get("bmi"), entry.get("body_fat"),
                            entry.get("visceral_fat"), entry.get("water"), entry.get("muscle"),
                            entry.get("bone_mass"), entry.get("protein_percentage"),
                            entry.get("bmr"), entry.get("body_score"),
                            entry.get("body_type"), entry.get("source")
                        ))
                        self.stats["weights"] += 1
            
            except Exception as e:
                self.stats["errors"].append(f"Weight file {filepath}: {e}")
        
        print(f"   ✅ Migrated {self.stats['weights']} weight records")
    
    def _migrate_blood_pressure(self, conn, limit: int = None):
        """Migrate blood pressure from CSV."""
        print("\n❤️  Migrating blood pressure logs...")
        
        if not BP_FILE.exists():
            print("   ⚠️  BP file not found, skipping")
            return
        
        with open(BP_FILE) as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break
                
                try:
                    measured_at = datetime.strptime(
                        row["Date"], "%Y-%m-%d %H:%M:%S %z"
                    )
                    
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO blood_pressure_logs (
                                user_id, measured_at, systolic, diastolic, source
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (user_id, measured_at) DO NOTHING
                        """, (
                            DEFAULT_USER_ID, measured_at,
                            int(row["Systolic"]), int(row["Diastolic"]),
                            row["Source"]
                        ))
                        self.stats["bp"] += 1
                
                except Exception as e:
                    self.stats["errors"].append(f"BP row {i}: {e}")
        
        print(f"   ✅ Migrated {self.stats['bp']} BP records")
    
    def _migrate_nutrition(self, conn, limit: int = None):
        """Migrate nutrition logs from JSON."""
        print("\n🍽️  Migrating nutrition logs...")
        
        if not NUTRITION_FILE.exists():
            print("   ⚠️  Nutrition file not found, skipping")
            return
        
        with open(NUTRITION_FILE) as f:
            data = json.load(f)
        
        entries = data.get("entries", [])
        if limit:
            entries = entries[:limit]
        
        for entry in entries:
            try:
                date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
                
                for meal in entry.get("meals", []):
                    with conn.cursor() as cur:
                        # Insert entry
                        cur.execute("""
                            INSERT INTO nutrition_entries (
                                user_id, date, meal_name, meal_time, had_workout
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            DEFAULT_USER_ID, date,
                            meal.get("meal"), meal.get("time"),
                            entry.get("had_workout", False)
                        ))
                        entry_id = cur.fetchone()[0]
                        self.stats["nutrition_entries"] += 1
                        
                        # Insert items
                        for item in meal.get("items", []):
                            cur.execute("""
                                INSERT INTO nutrition_items (
                                    entry_id, food, amount, unit,
                                    calories, protein, fats, carbs, note
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                entry_id, item.get("food"),
                                item.get("amount"), item.get("unit", "г"),
                                item.get("calories"), item.get("protein"),
                                item.get("fats"), item.get("carbs"),
                                item.get("note")
                            ))
                            self.stats["nutrition_items"] += 1
            
            except Exception as e:
                self.stats["errors"].append(f"Nutrition entry {entry.get('date')}: {e}")
        
        print(f"   ✅ Migrated {self.stats['nutrition_entries']} entries, {self.stats['nutrition_items']} items")
    
    def _print_stats(self):
        """Print migration statistics."""
        print("\n" + "="*60)
        print("📈 MIGRATION SUMMARY")
        print("="*60)
        print(f"Weights:           {self.stats['weights']}")
        print(f"Blood Pressure:    {self.stats['bp']}")
        print(f"Nutrition Entries: {self.stats['nutrition_entries']}")
        print(f"Nutrition Items:   {self.stats['nutrition_items']}")
        
        if self.stats["errors"]:
            print(f"\n⚠️  ERRORS ({len(self.stats['errors'])}):")
            for err in self.stats["errors"][:10]:  # Show first 10
                print(f"  - {err}")


def main():
    parser = argparse.ArgumentParser(description="Migrate HealthVault data to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no writes)")
    parser.add_argument("--limit", type=int, help="Limit records per type")
    parser.add_argument(
        "--db-url",
        default="postgresql://healthvault:dev_password_123@localhost:5432/healthvault",
        help="Database connection string"
    )
    args = parser.parse_args()
    
    try:
        migrator = DatabaseMigrator(args.db_url, dry_run=args.dry_run)
        migrator.migrate(limit=args.limit)
        print("\n✅ Migration completed successfully!")
        return 0
    
    except Exception as e:
        print(f"\n❌ Migration failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
