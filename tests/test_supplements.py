import pytest
from datetime import datetime, timedelta
from database.models import SupplementLog
from database.crud import create_supplement_log
from core.supplements import save_supplements, get_today_supplements, SupplementService
from unittest.mock import patch

# Setup in-memory SQLite database
TEST_DATABASE_URL = "sqlite:///:memory:"

# Fixtures are now in conftest.py

def test_save_supplements_current_day(mock_session_local):
    """Test saving supplements for today"""
    items = ["Vitamin D", "Omega-3"]
    user_id = 12345
    
    result = save_supplements(items, user_id=user_id)
    assert result is True
    
    # Verify in DB
    logs = mock_session_local.query(SupplementLog).filter(SupplementLog.user_id == user_id).all()
    assert len(logs) == 2
    names = [log.supplement_name for log in logs]
    assert "Vitamin D" in names
    assert "Omega-3" in names
    assert logs[0].date == datetime.now().date()

def test_save_supplements_yesterday(mock_session_local):
    """Test saving supplements for yesterday"""
    yesterday = (datetime.now() - timedelta(days=1)).date()
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    items = ["Psyllium"]
    user_id = 12345
    
    result = save_supplements(items, user_id=user_id, date_str=yesterday_str)
    assert result is True
    
    # Verify in DB
    log = mock_session_local.query(SupplementLog).filter(
        SupplementLog.user_id == user_id,
        SupplementLog.date == yesterday
    ).first()
    
    assert log is not None
    assert log.supplement_name == "Psyllium"

def test_save_multiple_times(mock_session_local):
    """Test appending to existing entries"""
    user_id = 12345
    save_supplements(["Zinc"], user_id=user_id)
    save_supplements(["Magnesium"], user_id=user_id)
    
    logs = mock_session_local.query(SupplementLog).filter(SupplementLog.user_id == user_id).all()
    assert len(logs) == 2
    names = [log.supplement_name for log in logs]
    assert "Zinc" in names
    assert "Magnesium" in names

def test_supplement_service_schedule():
    """Test supplement service detailed schedule"""
    test_user_id = 895655
    service = SupplementService(user_id=test_user_id)
    schedule = service.get_detailed_schedule()
    
    # Check that schedule contains expected sections
    assert "<b>☀️ УТРО (до еды)</b>" in schedule
    assert "<b>🌅 УТРО (с завтраком)</b>" in schedule
    assert "<b>🌙 ВЕЧЕР (с ужином)</b>" in schedule
    
    # Check that schedule contains vitamins (with either ✅ or ⬜)
    assert "Витамин D3" in schedule
    assert "Омега 3-6-9" in schedule
    assert "Псиллиум" in schedule
    assert "Магний" in schedule
    assert "Цинк" in schedule
    
    # Test that synonym matching works
    save_supplements(["Псиллиум"], user_id=test_user_id)
    updated_schedule = service.get_detailed_schedule()
    assert "✅ Псиллиум" in updated_schedule

