"""Helpers to determine which dashboard blocks have data.

Used by dashboard_generator.py to skip sections rather than showing
empty placeholders — important for new cohort users (Andrey, Elen) who
have no Garmin, no blood tests, no Netatmo sensor.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import ActivityLog, NutritionLog, User, Weight


def _cutoff(days: int = 30) -> date:
    return date.today() - timedelta(days=days)


def has_garmin_data(db: Session, user: User) -> bool:
    """True if user has Garmin email set OR any activity_log rows in last 30 days."""
    if user.garmin_email:
        return True
    return (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == user.telegram_id,
            ActivityLog.date >= _cutoff(30),
        )
        .first()
        is not None
    )


def has_apple_health_data(db: Session, user: User) -> bool:
    """True if user has any blood_pressure_logs rows (typically from HAE).

    blood_pressure_logs is not modelled in models.py so we use raw SQL.
    """
    row = db.execute(
        text("SELECT 1 FROM blood_pressure_logs WHERE user_id=:uid LIMIT 1"),
        {"uid": user.telegram_id},
    ).fetchone()
    return row is not None


def has_blood_test_data(db: Session, user: User) -> bool:
    """True if user has any blood test data.

    Checks for per-user biomarkers_{telegram_id}.json first (all cohorts),
    then falls back to owner's knowledge_base.json for backward compatibility.
    """
    import json

    # Per-user biomarkers file — works for any cohort
    bio_path = Path(__file__).resolve().parent / f"biomarkers_{user.telegram_id}.json"
    if bio_path.exists():
        try:
            bio = json.loads(bio_path.read_text())
            if any(isinstance(v, dict) and v.get("value") is not None for k, v in bio.items() if k != "_meta"):
                return True
        except Exception:
            pass

    # Legacy: owner's knowledge_base.json
    if user.cohort == "owner":
        kb_path = Path(__file__).resolve().parents[1] / "knowledge_base.json"
        if not kb_path.exists():
            return False
        try:
            kb = json.loads(kb_path.read_text())
            for entry in kb.get("blood_tests", []):
                if entry.get("values"):
                    return True
        except Exception:
            pass

    return False


def has_nutrition_data(db: Session, user: User) -> bool:
    """True if user has any nutrition_log rows."""
    return db.query(NutritionLog).filter(NutritionLog.user_id == user.telegram_id).first() is not None


def has_weight_data(db: Session, user: User) -> bool:
    """True if user has any weight measurements."""
    return db.query(Weight).filter(Weight.user_id == user.telegram_id).first() is not None


def get_available_blocks(db: Session, user: User) -> dict:
    """Return dict of block_name -> bool for all dashboard sections.

    Used at the start of generate_dashboard_html() to decide which blocks
    to include in the rendered payload.  Blocks set to False are skipped
    entirely — the template already reads meta.capabilities for this.
    """
    garmin = has_garmin_data(db, user)
    apple = has_apple_health_data(db, user)
    return {
        "body": has_weight_data(db, user),
        "nutrition": has_nutrition_data(db, user),
        "sport": garmin,
        "sleep": garmin,
        "heart": garmin or apple,
        "blood_tests": has_blood_test_data(db, user),
        "blood_pressure": apple,
        # Netatmo air quality — only the owner has the sensor
        "air": user.cohort == "owner",
    }
