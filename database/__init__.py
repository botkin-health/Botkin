# Database connection and session management

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from database.models import Base

load_dotenv()

# Database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://healthvault:dev_password_123@localhost:5432/healthvault')

# Create engine
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    pool_pre_ping=True,  # Verify connections before using
    pool_size=5,
    max_overflow=10
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
    create_user,
    update_user_last_active,
    generate_health_token,
    
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
    # User products (мои продукты)
    get_user_products,
    add_user_product,
    add_product_variant,
    update_product_average_from_variants,
    match_user_product,
)

__all__ = [
    'SessionLocal',
    'init_db',
    'get_db',
    'get_user_by_telegram_id',
    'get_user_by_health_token',
    'create_user',
    'update_user_last_active',
    'generate_health_token',
    'create_nutrition_log',
    'get_nutrition_logs_by_date',
    'get_nutrition_logs_by_period',
    'get_activity_logs_by_period',
    'get_last_activity_date',
    'get_nutrition_totals_by_date',
    'delete_nutrition_log',
    'create_weight',
    'get_latest_weight',
    'get_weights_by_period',
    'get_weight_stats',
    'create_supplement_log',
    'get_supplements_by_date',
    'get_supplements_by_period',
    'create_or_update_activity',
    'get_activity_by_date',
    'get_activities_by_period',
    'get_average_activity_stats',
    'create_blood_test',
    'get_latest_blood_test',
    'get_blood_tests_by_period',
    'get_all_blood_tests',
    'create_body_measurement',
    'get_user_products',
    'add_user_product',
    'add_product_variant',
    'update_product_average_from_variants',
    'match_user_product',
]
