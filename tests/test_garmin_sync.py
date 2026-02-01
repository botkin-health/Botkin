
import pytest
from unittest.mock import MagicMock, patch
from datetime import date
from core.garmin_data import sync_garmin_data
from database.models import ActivityLog
from database.crud import get_activity_by_date

# Mock Garmin response data
MOCK_GARMIN_STATS = {
    'totalKilocalories': 2500.0,
    'activeKilocalories': 500.0,
    'bmrKilocalories': 2000.0,
    'dailyStepCount': 10000,
    'totalDistanceMeters': 8000.0,
    'userDailySummaryId': 12345,
    'calendarDate': date.today().strftime('%Y-%m-%d')
}

def test_sync_garmin_data_populates_db(test_db, mock_session_local):
    """
    Test that sync_garmin_data calls Garmin API and saves data to DB.
    """
    user_id = 895655
    today_date = date.today()
    
    # We need to mock 'garminconnect.Garmin' because it is imported inside the function
    # But since we cannot rely on it being imported at module level in core/garmin_data.py
    # we patch 'garminconnect.Garmin' directly.
    
    # Patch SessionLocal in core.garmin_data to use our test db
    with patch('core.garmin_data.SessionLocal', return_value=test_db):
        with patch('garminconnect.Garmin') as MockGarmin:
            mock_client = MockGarmin.return_value
            mock_client.login.return_value = True
            mock_client.get_stats.return_value = MOCK_GARMIN_STATS
            
            # We also need to mock environment variables if they are missing
            with patch('os.getenv') as mock_getenv:
                def get_env_side_effect(key, default=None):
                    if key == 'GARMIN_EMAIL': return 'test@test.com'
                    if key == 'GARMIN_PASSWORD': return 'secret'
                    return default
                mock_getenv.side_effect = get_env_side_effect
                
                # Call sync
                sync_garmin_data(user_id)
            
            # Verify it tried to fetch data
            mock_client.get_stats.assert_called()
        
        # Verify DB population
        activity = get_activity_by_date(test_db, user_id, today_date)
        
        if not activity:
            pytest.fail("ActivityLog was not created after sync")
            
        assert activity.active_calories == 500.0
        assert activity.total_calories == 2500.0
        assert activity.steps == 10000
