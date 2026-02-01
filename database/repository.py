#!/usr/bin/env python3
"""
Database repository layer for HealthVault bot.
Provides CRUD operations for Postgres with JSON backup fallback.
"""

import os
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

# Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://healthvault:dev_password_123@localhost:5432/healthvault"
)
DEFAULT_USER_ID = 895655  # Single-user mode (CORRECT TELEGRAM ID)


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()


class WeightRepository:
    """Repository for weight logs."""
    
    @staticmethod
    def save(weight_data: Dict[str, Any], user_id: int = DEFAULT_USER_ID) -> Optional[int]:
        """
        Save weight record to Postgres.
        
        Args:
            weight_data: Dict with keys: date, weight, bmi, body_fat, etc.
            user_id: Telegram user ID
            
        Returns:
            Record ID if successful, None otherwise
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Parse timestamp
                    if isinstance(weight_data.get("date"), str):
                        try:
                            measured_at = datetime.strptime(
                                weight_data["date"], "%Y-%m-%d %H:%M"
                            )
                        except ValueError:
                            measured_at = datetime.strptime(
                                weight_data["date"], "%Y-%m-%d"
                            )
                    else:
                        measured_at = weight_data.get("date", datetime.now())
                    
                    cur.execute("""
                        INSERT INTO weight_logs (
                            user_id, measured_at, weight, bmi, body_fat,
                            visceral_fat, water, muscle, bone_mass,
                            protein_percentage, bmr, body_score, body_type, source
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, measured_at) DO UPDATE SET
                            weight = EXCLUDED.weight,
                            bmi = EXCLUDED.bmi,
                            body_fat = EXCLUDED.body_fat,
                            visceral_fat = EXCLUDED.visceral_fat,
                            water = EXCLUDED.water,
                            muscle = EXCLUDED.muscle,
                            bone_mass = EXCLUDED.bone_mass,
                            protein_percentage = EXCLUDED.protein_percentage,
                            bmr = EXCLUDED.bmr,
                            body_score = EXCLUDED.body_score,
                            body_type = EXCLUDED.body_type,
                            source = EXCLUDED.source
                        RETURNING id
                    """, (
                        user_id, measured_at,
                        weight_data.get("weight"),
                        weight_data.get("bmi"),
                        weight_data.get("body_fat"),
                        weight_data.get("visceral_fat"),
                        weight_data.get("water"),
                        weight_data.get("muscle"),
                        weight_data.get("bone_mass"),
                        weight_data.get("protein_percentage"),
                        weight_data.get("bmr"),
                        weight_data.get("body_score"),
                        weight_data.get("body_type"),
                        weight_data.get("source", "telegram_bot")
                    ))
                    return cur.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save weight to Postgres: {e}")
            return None
    
    @staticmethod
    def get_latest(user_id: int = DEFAULT_USER_ID) -> Optional[Dict[str, Any]]:
        """Get latest weight record."""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM weight_logs
                        WHERE user_id = %s
                        ORDER BY measured_at DESC
                        LIMIT 1
                    """, (user_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            print(f"❌ Failed to get latest weight: {e}")
            return None
    
    @staticmethod
    def get_by_date_range(
        start_date: date,
        end_date: date,
        user_id: int = DEFAULT_USER_ID
    ) -> List[Dict[str, Any]]:
        """Get weight records in date range."""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM weight_logs
                        WHERE user_id = %s
                        AND measured_at::date BETWEEN %s AND %s
                        ORDER BY measured_at DESC
                    """, (user_id, start_date, end_date))
                    return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            print(f"❌ Failed to get weights by date range: {e}")
            return []


class BloodPressureRepository:
    """Repository for blood pressure logs."""
    
    @staticmethod
    def save(bp_data: Dict[str, Any], user_id: int = DEFAULT_USER_ID) -> Optional[int]:
        """Save BP record to Postgres."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    measured_at = bp_data.get("measured_at", datetime.now())
                    if isinstance(measured_at, str):
                        measured_at = datetime.fromisoformat(measured_at)
                    
                    cur.execute("""
                        INSERT INTO blood_pressure_logs (
                            user_id, measured_at, systolic, diastolic, heart_rate, source
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, measured_at) DO UPDATE SET
                            systolic = EXCLUDED.systolic,
                            diastolic = EXCLUDED.diastolic,
                            heart_rate = EXCLUDED.heart_rate,
                            source = EXCLUDED.source
                        RETURNING id
                    """, (
                        user_id, measured_at,
                        bp_data.get("systolic"),
                        bp_data.get("diastolic"),
                        bp_data.get("heart_rate"),
                        bp_data.get("source", "telegram_bot")
                    ))
                    return cur.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save BP to Postgres: {e}")
            return None


class NutritionRepository:
    """Repository for nutrition logs."""
    
    @staticmethod
    def save_meal(
        meal_date: date,
        meal_name: str,
        items: List[Dict[str, Any]],
        meal_time: Optional[str] = None,
        had_workout: bool = False,
        user_id: int = DEFAULT_USER_ID
    ) -> Optional[int]:
        """
        Save nutrition entry with items.
        
        Args:
            meal_date: Date of meal
            meal_name: Name of meal (e.g., "Завтрак")
            items: List of food items with calories, protein, etc.
            meal_time: Time of meal (HH:MM)
            had_workout: Whether user had workout that day
            
        Returns:
            Entry ID if successful, None otherwise
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Insert entry
                    cur.execute("""
                        INSERT INTO nutrition_entries (
                            user_id, date, meal_name, meal_time, had_workout
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """, (user_id, meal_date, meal_name, meal_time, had_workout))
                    entry_id = cur.fetchone()[0]
                    
                    # Insert items
                    for item in items:
                        cur.execute("""
                            INSERT INTO nutrition_items (
                                entry_id, food, amount, unit,
                                calories, protein, fats, carbs, note
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            entry_id,
                            item.get("food"),
                            item.get("amount"),
                            item.get("unit", "г"),
                            item.get("calories"),
                            item.get("protein"),
                            item.get("fats"),
                            item.get("carbs"),
                            item.get("note")
                        ))
                    
                    return entry_id
        except Exception as e:
            print(f"❌ Failed to save nutrition to Postgres: {e}")
            return None
    
    @staticmethod
    def get_daily_totals(target_date: date, user_id: int = DEFAULT_USER_ID) -> Dict[str, float]:
        """Get daily nutrition totals."""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            COALESCE(SUM(ni.calories), 0) as total_calories,
                            COALESCE(SUM(ni.protein), 0) as total_protein,
                            COALESCE(SUM(ni.fats), 0) as total_fats,
                            COALESCE(SUM(ni.carbs), 0) as total_carbs
                        FROM nutrition_entries ne
                        JOIN nutrition_items ni ON ne.id = ni.entry_id
                        WHERE ne.user_id = %s AND ne.date = %s
                    """, (user_id, target_date))
                    result = cur.fetchone()
                    return dict(result) if result else {
                        "total_calories": 0,
                        "total_protein": 0,
                        "total_fats": 0,
                        "total_carbs": 0
                    }
        except Exception as e:
            print(f"❌ Failed to get daily totals: {e}")
            return {"total_calories": 0, "total_protein": 0, "total_fats": 0, "total_carbs": 0}


# Convenience instances
weights = WeightRepository()
blood_pressure = BloodPressureRepository()
nutrition = NutritionRepository()
