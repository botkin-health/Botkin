# Database connection and session management

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from database.models import Base

load_dotenv()

# Database URL from environment — required, no hardcoded fallback.
# Раньше тут был дефолт с паролем (репозиторий публичный) — удалён.
# Конфигурируется через .env / .env.production / переменную окружения.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не задана. Укажите её через окружение (.env / .env.production). "
        "Дефолт намеренно не предусмотрен, чтобы не коммитить креды в открытый код."
    )

# Create engine
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    pool_pre_ping=True,  # Verify connections before using
    pool_size=5,
    max_overflow=10,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database - create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Export CRUD operations for easy access
from database.crud import (
    # User operations
    get_user_by_telegram_id,
    get_user_by_health_token,
    get_user_by_share_token,
    create_user,
    update_user_last_active,
    generate_health_token,
    generate_share_token,
    reset_share_token,
    # Nutrition operations
    create_nutrition_log,
    get_nutrition_logs_by_date,
    get_nutrition_logs_by_period,
    get_activity_logs_by_period,
    get_last_activity_date,
    get_nutrition_totals_by_date,
    delete_nutrition_log,
    # Weight operations
    create_weight,
    upsert_manual_weight,
    get_latest_weight,
    get_weights_by_period,
    get_weight_stats,
    # Supplement operations
    create_supplement_log,
    get_supplements_by_date,
    get_supplements_by_period,
    # Activity operations
    create_or_update_activity,
    get_activity_by_date,
    get_activities_by_period,
    get_average_activity_stats,
    # Blood test operations
    create_blood_test,
    get_latest_blood_test,
    get_blood_tests_by_period,
    get_all_blood_tests,
    create_body_measurement,
    # Verified products (#255)
    get_verified_products,
    find_verified_product,
    upsert_verified_product,
    increment_verified_product_usage,
)

__all__ = [
    "SessionLocal",
    "init_db",
    "get_db",
    "get_user_by_telegram_id",
    "get_user_by_health_token",
    "get_user_by_share_token",
    "create_user",
    "update_user_last_active",
    "generate_health_token",
    "generate_share_token",
    "reset_share_token",
    "create_nutrition_log",
    "get_nutrition_logs_by_date",
    "get_nutrition_logs_by_period",
    "get_activity_logs_by_period",
    "get_last_activity_date",
    "get_nutrition_totals_by_date",
    "delete_nutrition_log",
    "create_weight",
    "upsert_manual_weight",
    "get_latest_weight",
    "get_weights_by_period",
    "get_weight_stats",
    "create_supplement_log",
    "get_supplements_by_date",
    "get_supplements_by_period",
    "create_or_update_activity",
    "get_activity_by_date",
    "get_activities_by_period",
    "get_average_activity_stats",
    "create_blood_test",
    "get_latest_blood_test",
    "get_blood_tests_by_period",
    "get_all_blood_tests",
    "create_body_measurement",
    "get_verified_products",
    "find_verified_product",
    "upsert_verified_product",
    "increment_verified_product_usage",
]
