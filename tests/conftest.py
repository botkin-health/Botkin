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
    """Patches SessionLocal in both core.supplements and services.nutrition_service"""
    # We patch where it is IMPORTED or USED.
    # Since they import SessionLocal from database, we might need to patch 'database.SessionLocal'
    # BUT they might have treated it as 'from database import SessionLocal'
    
    # Let's patch in the specific modules for safety
    p1 = patch("core.supplements.SessionLocal", return_value=test_db)
    p2 = patch("services.nutrition_service.SessionLocal", return_value=test_db)
    
    # Start patches
    p1.start()
    p2.start()
    
    yield test_db
    
    # Stop patches
    p1.stop()
    p2.stop()
