"""
CRUD operations for HealthVault database

This module provides database operations for all tables:
- Users: create, get, update, list
- NutritionLog: create, get by date/period, update, delete
- Weights: create, get latest, get by period
- Supplements: create, get by date/period
- ActivityLog: create/update, get by date/period
- BloodTests: create, get latest, get all
"""

from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc

from database.models import User, NutritionLog, Weight, SupplementLog, ActivityLog, BloodTest


# ==================== USER OPERATIONS ====================

def get_user_by_telegram_id(db: Session, telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID"""
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def get_user_by_health_token(db: Session, health_token: str) -> Optional[User]:
    """Get user by Apple Health API token"""
    return db.query(User).filter(User.health_token == health_token).first()


def create_user(
    db: Session,
    telegram_id: int,
    first_name: Optional[str] = None,
    username: Optional[str] = None,
    role: str = 'user'
) -> User:
    """Create a new user"""
    user = User(
        telegram_id=telegram_id,
        first_name=first_name,
        username=username,
        role=role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_last_active(db: Session, telegram_id: int):
    """Update user's last_active timestamp"""
    user = get_user_by_telegram_id(db, telegram_id)
    if user:
        user.last_active = datetime.now()
        db.commit()


def generate_health_token(db: Session, telegram_id: int) -> str:
    """Generate and save a unique Apple Health API token for user"""
    import secrets
    token = f"hvt_{telegram_id}_{secrets.token_hex(16)}"
    
    user = get_user_by_telegram_id(db, telegram_id)
    if user:
        user.health_token = token
        db.commit()
    
    return token


# ==================== NUTRITION LOG OPERATIONS ====================

def create_nutrition_log(
    db: Session,
    user_id: int,
    date: date,
    meal_time: Optional[time],
    meal_name: str,
    items: List[Dict],
    totals: Dict,
    photo_paths: Optional[List[str]] = None
) -> NutritionLog:
    """Create a new nutrition log entry"""
    log = NutritionLog(
        user_id=user_id,
        date=date,
        meal_time=meal_time,
        meal_name=meal_name,
        items=items,
        totals=totals,
        photo_paths=photo_paths or []
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_nutrition_logs_by_date(db: Session, user_id: int, date: date) -> List[NutritionLog]:
    """Get all nutrition logs for a specific date"""
    return db.query(NutritionLog).filter(
        NutritionLog.user_id == user_id,
        NutritionLog.date == date
    ).order_by(NutritionLog.meal_time).all()


def get_nutrition_logs_by_period(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date
) -> List[NutritionLog]:
    """Get nutrition logs for a date range"""
    return db.query(NutritionLog).filter(
        NutritionLog.user_id == user_id,
        NutritionLog.date >= start_date,
        NutritionLog.date <= end_date
    ).order_by(NutritionLog.date, NutritionLog.meal_time).all()


def get_activity_logs_by_period(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date
) -> List[ActivityLog]:
    """Get activity logs (Garmin data) for a date range"""
    return db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.date >= start_date,
        ActivityLog.date <= end_date
    ).order_by(ActivityLog.date).all()


def get_nutrition_totals_by_date(db: Session, user_id: int, date: date) -> Dict:
    """Calculate total nutrition for a specific date"""
    logs = get_nutrition_logs_by_date(db, user_id, date)
    
    total = {
        'calories': 0,
        'protein': 0,
        'fats': 0,
        'carbs': 0,
        'fiber': 0
    }
    
    for log in logs:
        totals = log.totals or {}
        total['calories'] += totals.get('calories', 0)
        total['protein'] += totals.get('protein', 0)
        total['fats'] += totals.get('fats', 0)
        total['carbs'] += totals.get('carbs', 0)
        total['fiber'] += totals.get('fiber', 0)
    
    return total


def delete_nutrition_log(db: Session, log_id: int, user_id: int) -> bool:
    """Delete a nutrition log entry"""
    log = db.query(NutritionLog).filter(
        NutritionLog.id == log_id,
        NutritionLog.user_id == user_id
    ).first()
    
    if log:
        db.delete(log)
        db.commit()
        return True
    return False


# ==================== WEIGHT OPERATIONS ====================

def create_weight(
    db: Session,
    user_id: int,
    measured_at: datetime,
    weight: float,
    body_fat: Optional[float] = None,
    muscle_mass: Optional[float] = None,
    water: Optional[float] = None,
    bmi: Optional[float] = None,
    visceral_fat: Optional[int] = None,
    bone_mass: Optional[float] = None,
    source: str = 'manual'
) -> Weight:
    """Create a new weight entry"""
    weight_entry = Weight(
        user_id=user_id,
        measured_at=measured_at,
        weight=weight,
        body_fat=body_fat,
        muscle_mass=muscle_mass,
        water=water,
        bmi=bmi,
        visceral_fat=visceral_fat,
        bone_mass=bone_mass,
        source=source
    )
    db.add(weight_entry)
    db.commit()
    db.refresh(weight_entry)
    return weight_entry


def get_latest_weight(db: Session, user_id: int) -> Optional[Weight]:
    """Get the most recent weight measurement"""
    return db.query(Weight).filter(
        Weight.user_id == user_id
    ).order_by(desc(Weight.measured_at)).first()


def get_weights_by_period(
    db: Session,
    user_id: int,
    start_date: datetime,
    end_date: datetime
) -> List[Weight]:
    """Get weight measurements for a date range"""
    return db.query(Weight).filter(
        Weight.user_id == user_id,
        Weight.measured_at >= start_date,
        Weight.measured_at <= end_date
    ).order_by(Weight.measured_at).all()


def get_weight_stats(db: Session, user_id: int, days: int = 30) -> Dict:
    """Get weight statistics for the last N days"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    weights = get_weights_by_period(db, user_id, start_date, end_date)
    
    if not weights:
        return {}
    
    weight_values = [w.weight for w in weights]
    
    return {
        'current': weights[-1].weight,
        'min': min(weight_values),
        'max': max(weight_values),
        'avg': sum(weight_values) / len(weight_values),
        'change': weights[-1].weight - weights[0].weight,
        'count': len(weights)
    }


# ==================== SUPPLEMENT LOG OPERATIONS ====================

def create_supplement_log(
    db: Session,
    user_id: int,
    date: date,
    time: Optional[time],
    supplement_name: str,
    dosage: Optional[str] = None
) -> SupplementLog:
    """Create a new supplement log entry"""
    log = SupplementLog(
        user_id=user_id,
        date=date,
        time=time,
        supplement_name=supplement_name,
        dosage=dosage
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_supplements_by_date(db: Session, user_id: int, date: date) -> List[SupplementLog]:
    """Get all supplements taken on a specific date"""
    return db.query(SupplementLog).filter(
        SupplementLog.user_id == user_id,
        SupplementLog.date == date
    ).order_by(SupplementLog.time).all()


def get_supplements_by_period(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date
) -> List[SupplementLog]:
    """Get supplements for a date range"""
    return db.query(SupplementLog).filter(
        SupplementLog.user_id == user_id,
        SupplementLog.date >= start_date,
        SupplementLog.date <= end_date
    ).order_by(SupplementLog.date, SupplementLog.time).all()


# ==================== ACTIVITY LOG OPERATIONS ====================

def create_or_update_activity(
    db: Session,
    user_id: int,
    date: date,
    steps: Optional[int] = None,
    active_calories: Optional[float] = None,
    total_calories: Optional[float] = None,
    bmr_calories: Optional[float] = None,
    distance_km: Optional[float] = None,
    sleep_hours: Optional[float] = None,
    heart_rate_avg: Optional[int] = None,
    hrv: Optional[int] = None,
    stress_level: Optional[int] = None,
    source: str = 'apple_health',
    raw_data: Optional[Dict] = None
) -> ActivityLog:
    """Create or update activity log for a specific date"""
    # Check if entry exists
    existing = db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.date == date
    ).first()
    
    if existing:
        # Update existing entry
        if steps is not None:
            existing.steps = steps
        if active_calories is not None:
            existing.active_calories = active_calories
        if total_calories is not None:
            existing.total_calories = total_calories
        if bmr_calories is not None:
            existing.bmr_calories = bmr_calories
        if distance_km is not None:
            existing.distance_km = distance_km
        if sleep_hours is not None:
            existing.sleep_hours = sleep_hours
        if heart_rate_avg is not None:
            existing.heart_rate_avg = heart_rate_avg
        if hrv is not None:
            existing.hrv = hrv
        if stress_level is not None:
            existing.stress_level = stress_level
        if raw_data is not None:
            existing.raw_data = raw_data
        
        existing.synced_at = datetime.now()
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Create new entry
        activity = ActivityLog(
            user_id=user_id,
            date=date,
            steps=steps,
            active_calories=active_calories,
            total_calories=total_calories,
            bmr_calories=bmr_calories,
            distance_km=distance_km,
            sleep_hours=sleep_hours,
            heart_rate_avg=heart_rate_avg,
            hrv=hrv,
            stress_level=stress_level,
            source=source,
            raw_data=raw_data
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return activity


def get_activity_by_date(db: Session, user_id: int, date: date) -> Optional[ActivityLog]:
    """Get activity log for a specific date"""
    return db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.date == date
    ).first()


def get_activities_by_period(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date
) -> List[ActivityLog]:
    """Get activity logs for a date range"""
    return db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.date >= start_date,
        ActivityLog.date <= end_date
    ).order_by(ActivityLog.date).all()


def get_average_activity_stats(db: Session, user_id: int, days: int = 14) -> Dict:
    """Get average activity stats for the last N days"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    activities = get_activities_by_period(db, user_id, start_date, end_date)
    
    if not activities:
        return {}
    
    valid_activities = [a for a in activities if a.total_calories and a.total_calories > 1200]
    
    if not valid_activities:
        return {}
    
    return {
        'active_calories': sum(a.active_calories or 0 for a in valid_activities) / len(valid_activities),
        'total_calories': sum(a.total_calories or 0 for a in valid_activities) / len(valid_activities),
        'bmr_calories': sum(a.bmr_calories or 0 for a in valid_activities) / len(valid_activities),
        'steps': sum(a.steps or 0 for a in valid_activities) / len(valid_activities),
        'count': len(valid_activities)
    }


# ==================== BLOOD TEST OPERATIONS ====================

def create_blood_test(
    db: Session,
    user_id: int,
    test_date: date,
    test_type: Optional[str],
    values: Dict,
    file_path: Optional[str] = None,
    status: str = 'current'
) -> BloodTest:
    """Create a new blood test entry"""
    test = BloodTest(
        user_id=user_id,
        test_date=test_date,
        test_type=test_type,
        values=values,
        file_path=file_path,
        status=status
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return test


def get_latest_blood_test(db: Session, user_id: int) -> Optional[BloodTest]:
    """Get the most recent blood test"""
    return db.query(BloodTest).filter(
        BloodTest.user_id == user_id,
        BloodTest.status == 'current'
    ).order_by(desc(BloodTest.test_date)).first()


def get_blood_tests_by_period(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date
) -> List[BloodTest]:
    """Get blood tests for a date range"""
    return db.query(BloodTest).filter(
        BloodTest.user_id == user_id,
        BloodTest.test_date >= start_date,
        BloodTest.test_date <= end_date
    ).order_by(BloodTest.test_date).all()


def get_all_blood_tests(db: Session, user_id: int) -> List[BloodTest]:
    """Get all blood tests for a user"""
    return db.query(BloodTest).filter(
        BloodTest.user_id == user_id
    ).order_by(desc(BloodTest.test_date)).all()


def get_last_activity_date(db: Session, user_id: int) -> Optional[date]:
    """Get the most recent date with activity data"""
    result = db.query(ActivityLog.date).filter(
        ActivityLog.user_id == user_id
    ).order_by(ActivityLog.date.desc()).first()
    return result[0] if result else None
