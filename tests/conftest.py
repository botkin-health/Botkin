import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base
from unittest.mock import patch

# Setup in-memory SQLite database
# Use check_same_thread=False for SQLite with threaded tests if needed
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_session_local(test_db):
    """Patches SessionLocal in all modules that use it in tests"""
    patches = [
        patch("core.supplements.SessionLocal", return_value=test_db),
        patch("services.nutrition_service.SessionLocal", return_value=test_db),
        patch("core.weekly_nutrition.SessionLocal", return_value=test_db),
        patch("core.garmin_data.SessionLocal", return_value=test_db),
    ]

    for p in patches:
        p.start()

    yield test_db

    for p in patches:
        p.stop()
