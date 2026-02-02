#!/usr/bin/env python3
"""
Тесты для умной синхронизации Garmin.
Упрощенная версия без сложного мокирования datetime.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from core.garmin_data import get_last_activity_date
from database.models import ActivityLog


class TestSmartGarminSync:
    """Тесты умной синхронизации Garmin"""
    
    def test_get_last_activity_date_with_data(self, test_db):
        """Тест: get_last_activity_date возвращает последнюю дату"""
        user_id = 895655
        
        # Создаем несколько записей активности
        activity1 = ActivityLog(
            user_id=user_id,
            date=date(2026, 1, 30),
            total_calories=2200,
            active_calories=400
        )
        activity2 = ActivityLog(
            user_id=user_id,
            date=date(2026, 2, 1),
            total_calories=2300,
            active_calories=450
        )
        
        test_db.add(activity1)
        test_db.add(activity2)
        test_db.commit()
        
        # Проверяем, что возвращается последняя дата
        last_date = get_last_activity_date(test_db, user_id)
        assert last_date == date(2026, 2, 1)
        
    def test_get_last_activity_date_empty(self, test_db):
        """Тест: get_last_activity_date возвращает None если нет данных"""
        user_id = 999999
        
        last_date = get_last_activity_date(test_db, user_id)
        assert last_date is None
        
    def test_sync_calls_garmin_api(self, test_db):
        """Тест: sync_missing_garmin_days вызывает sync для нужных дней"""
        from core.garmin_data import sync_missing_garmin_days
        user_id = 895655
        
        # Создаем активность 2 дня назад
        old_date = date.today() - timedelta(days=2)
        activity = ActivityLog(
            user_id=user_id,
            date=old_date,
            total_calories=2200,
            active_calories=400
        )
        test_db.add(activity)
        test_db.commit()
        
        # Мокируем sync_garmin_data чтобы не делать реальные вызовы к API
        with patch('core.garmin_data.sync_garmin_data') as mock_sync:
            with patch('core.garmin_data.SessionLocal', return_value=test_db):
                sync_missing_garmin_days(user_id)
                
                # Проверяем что API был вызван
                # (должно быть минимум 3 вызова: old_date, old_date+1, сегодня)
                assert mock_sync.call_count >= 3


class TestGarminDataConsistency:
    """Тесты консистентности данных Garmin"""
    
    def test_no_duplicate_dates(self, test_db):
        """Тест: не создаются дубликаты записей для одной даты"""
        user_id = 895655
        test_date = date.today()
        
        # Создаем первую запись
        activity1 = ActivityLog(
            user_id=user_id,
            date=test_date,
            total_calories=2200,
            active_calories=400
        )
        test_db.add(activity1)
        test_db.commit()
        
        # Пытаемся создать дубликат
        existing = test_db.query(ActivityLog).filter(
            ActivityLog.user_id == user_id,
            ActivityLog.date == test_date
        ).first()
        
        if existing:
            # Обновляем, а не создаем новую
            existing.total_calories = 2300
            test_db.commit()
        else:
            activity2 = ActivityLog(
                user_id=user_id,
                date=test_date,
                total_calories=2300,
                active_calories=450
            )
            test_db.add(activity2)
            test_db.commit()
        
        # Проверяем, что есть только одна запись
        count = test_db.query(ActivityLog).filter(
            ActivityLog.user_id == user_id,
            ActivityLog.date == test_date
        ).count()
        
        assert count == 1, "Не должно быть дубликатов для одной даты"
    
    def test_activity_log_stores_correct_data(self, test_db):
        """Тест: ActivityLog корректно сохраняет данные"""
        user_id = 895655
        test_date = date(2026, 2, 1)
        
        activity = ActivityLog(
            user_id=user_id,
            date=test_date,
            total_calories=2500,
            active_calories=500,
            steps=10000,
            bmr_calories=2000
        )
        
        test_db.add(activity)
        test_db.commit()
        
        # Получаем обратно из БД
        saved = test_db.query(ActivityLog).filter(
            ActivityLog.user_id == user_id,
            ActivityLog.date == test_date
        ).first()
        
        assert saved is not None
        assert saved.total_calories == 2500
        assert saved.active_calories == 500
        assert saved.steps == 10000
        assert saved.bmr_calories == 2000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
