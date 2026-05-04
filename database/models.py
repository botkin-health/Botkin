# Database Models for HealthVault Multi-user

from datetime import date, datetime, time
from typing import Optional, List
from sqlalchemy import (
    String,
    Integer,
    SmallInteger,
    BigInteger,
    Float,
    Boolean,
    DateTime,
    Date,
    Time,
    JSON,
    Text,
    ARRAY,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models"""

    pass


class SafeArray(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return ARRAY(Text)
        return JSON()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("cohort IN ('owner','family','early_user','external')", name="ck_users_cohort"),
        CheckConstraint("pack_name IN ('generic','cardiac','bariatric','female-cycle')", name="ck_users_pack_name"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    role: Mapped[str] = mapped_column(String(50), default="user", server_default="user")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow", server_default="Europe/Moscow")

    # Apple Health token for API authentication
    health_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)

    # Share token for public dashboard (security by obscurity)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)

    # Garmin credentials (encrypted in production)
    garmin_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    garmin_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Biometric profile — needed for medical calculations (BMI, PhenoAge, LE8, Framingham)
    # Set once during /setup; required for panels to show meaningful scores.
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    height_cm: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    sex: Mapped[str] = mapped_column(String(10), default="male", server_default="male")

    # Manual calorie targets (for users without Garmin)
    bmr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Базовый метаболизм, ккал/день
    avg_active_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Средние активные калории
    target_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Целевой вес для расчёта макросов

    # Multi-user cohort / container / pack / BYOK fields (Sprint 1a)
    cohort: Mapped[str] = mapped_column(String(20), default="external", server_default="external")
    container_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    container_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pack_name: Mapped[str] = mapped_column(String(50), default="generic", server_default="generic")
    jwt_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    encrypted_openai_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_anthropic_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    nutrition_logs: Mapped[List["NutritionLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weights: Mapped[List["Weight"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    supplements: Mapped[List["SupplementLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    activities: Mapped[List["ActivityLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    blood_tests: Mapped[List["BloodTest"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    body_measurements: Mapped[List["BodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class NutritionLog(Base):
    __tablename__ = "nutrition_log"
    __table_args__ = (
        UniqueConstraint("user_id", "date", "meal_time", "meal_name", name="uq_nutrition_user_date_meal"),
        Index("idx_nutrition_user_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    meal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    items: Mapped[dict] = mapped_column(JSON, nullable=False)  # JSONB in PostgreSQL
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    photo_paths: Mapped[Optional[List[str]]] = mapped_column(SafeArray, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped["User"] = relationship(back_populates="nutrition_logs")


# UserProduct + UserProductVariant models removed Apr 2026 (/my_products feature retired).
# DB tables user_products + user_product_variants are dropped in the matching migration.


class Weight(Base):
    __tablename__ = "weights"
    __table_args__ = (
        UniqueConstraint("user_id", "measured_at", name="uq_weight_user_datetime"),
        Index("idx_weights_user_date", "user_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    body_fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    muscle_mass: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    water: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bmi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    visceral_fat: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bone_mass: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # 'apple_health', 'zepp', 'manual', 'screenshot_ocr'

    # Relationship
    user: Mapped["User"] = relationship(back_populates="weights")


class SupplementLog(Base):
    __tablename__ = "supplements_log"
    __table_args__ = (Index("idx_supplements_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    supplement_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped["User"] = relationship(back_populates="supplements")


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_activity_user_date"),
        Index("idx_activity_user_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bmr_calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sleep_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heart_rate_avg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hrv: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stress_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="apple_health", server_default="apple_health")
    raw_data: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )  # For storing full Garmin/Apple Health payload
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped["User"] = relationship(back_populates="activities")


class BloodTest(Base):
    __tablename__ = "blood_tests"
    __table_args__ = (Index("idx_blood_tests_user_date", "user_id", "test_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    test_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # "Биохимия", "Гормоны"
    values: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"cholesterol": 5.66, "LDL": 3.2, ...}
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Path to PDF file
    status: Mapped[str] = mapped_column(String(50), default="current", server_default="current")  # current, historical
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped["User"] = relationship(back_populates="blood_tests")


class BodyMeasurement(Base):
    __tablename__ = "body_measurements"
    __table_args__ = (Index("idx_measurements_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    waist_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    neck_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hips_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    chest_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thigh_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    biceps_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped["User"] = relationship(back_populates="body_measurements")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    show_calorie_budget_bar: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # BMR resolution mode:
    #   'auto'   — use Garmin → Apple Health → default (live data from wearables)
    #   'manual' — use bmr_override + activity_avg_override (user-entered, Mifflin-St Jeor)
    bmr_source: Mapped[str] = mapped_column(String(10), default="auto", server_default="auto")
    bmr_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    activity_avg_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Activity level for Mifflin-St Jeor PAL multiplier (sedentary/light/moderate/high)
    activity_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    target_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_weight_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Calorie goal: signed % relative to maintenance.
    # -15 = 15% deficit (lose weight), 0 = maintenance, +10 = 10% surplus (gain).
    calorie_goal_pct: Mapped[int] = mapped_column(Integer, default=-15, server_default="-15")
    supplement_reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    supplement_reminder_time: Mapped[time] = mapped_column(Time, server_default="08:00:00")
    supplements: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="settings")
