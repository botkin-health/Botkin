#!/usr/bin/env python3
"""
Import blood pressure data from Apple Health CSV to PostgreSQL.

Source: data/apple-health/parsed/blood_pressure_manual.csv
Target: blood_pressure_logs table

Usage:
    python scripts/import_blood_pressure.py
    python scripts/import_blood_pressure.py --db-url postgresql://healthvault:dev_password_123@116.203.213.137:5432/healthvault
    python scripts/import_blood_pressure.py --dry-run
"""

import csv
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

import psycopg2

ROOT = Path(__file__).parent.parent
CSV_PATH = ROOT / "data/apple-health/parsed/blood_pressure_manual.csv"
USER_ID = 895655


def parse_date(date_str: str) -> datetime:
    """Parse '2026-02-01 09:54:29 +0300' → datetime (naive, already in MSK)."""
    # Strip timezone suffix and parse as naive datetime
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            # Strip tzinfo — store as local (MSK) naive datetime, consistent with other tables
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


def load_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "measured_at": parse_date(row["Date"]),
                    "systolic": int(row["Systolic"]),
                    "diastolic": int(row["Diastolic"]),
                    "source": row.get("Source", "apple_health").strip() or "apple_health",
                })
            except Exception as e:
                print(f"⚠️  Skipping row {row}: {e}")
    return rows


def import_to_db(rows: list[dict], db_url: str, dry_run: bool) -> tuple[int, int]:
    inserted = updated = 0

    if dry_run:
        print(f"[DRY RUN] Would import {len(rows)} records")
        for r in rows[:5]:
            print(f"  {r}")
        return 0, 0

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                    INSERT INTO blood_pressure_logs
                        (user_id, measured_at, systolic, diastolic, heart_rate, source)
                    VALUES (%s, %s, %s, %s, NULL, %s)
                    ON CONFLICT (user_id, measured_at) DO UPDATE SET
                        systolic   = EXCLUDED.systolic,
                        diastolic  = EXCLUDED.diastolic,
                        source     = EXCLUDED.source
                    RETURNING (xmax = 0) AS was_inserted
                """, (USER_ID, r["measured_at"], r["systolic"], r["diastolic"], r["source"]))
                was_inserted = cur.fetchone()[0]
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
        conn.commit()
    finally:
        conn.close()

    return inserted, updated


def main():
    parser = argparse.ArgumentParser(description="Import blood pressure CSV → PostgreSQL")
    parser.add_argument(
        "--db-url",
        default=os.getenv(
            "DATABASE_URL",
            "postgresql://healthvault:dev_password_123@116.203.213.137:5432/healthvault"
        ),
        help="PostgreSQL connection URL"
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")
    args = parser.parse_args()

    if not CSV_PATH.exists():
        print(f"❌ CSV not found: {CSV_PATH}")
        sys.exit(1)

    rows = load_csv(CSV_PATH)
    print(f"📄 Loaded {len(rows)} records from CSV")
    if rows:
        dates = [r["measured_at"] for r in rows]
        print(f"   Range: {min(dates).date()} → {max(dates).date()}")

    inserted, updated = import_to_db(rows, args.db_url, args.dry_run)

    if not args.dry_run:
        print(f"✅ Done: {inserted} inserted, {updated} updated")


if __name__ == "__main__":
    main()
