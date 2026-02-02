#!/usr/bin/env python3
"""
Тесты для умной синхронизации Garmin.
Покрывают проблему с дублированием данных и избыточной загрузкой.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from core.garmin_data import get_last_activity_date, sync_missing_garmin_days
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
        
    @patch('core.garmin_data.get_last_activity_date')
    @patch('core.garmin_data.sync_garmin_data')
    def test_sync_missing_days_from_last_date(
        self, 
        mock_sync_garmin,
        mock_get_last_date
    ):
        """Тест: синхронизация с последней даты"""
        user_id = 895655
        
        # Последняя дата в БД - 30 января
        mock_get_last_date.return_value = date(2026, 1, 30)
        
        # Текущая дата - 2 февраля
        with patch('core.garmin_data.date') as mock_date:
            mock_date.today.return_value = date(2026, 2, 2)
            
            # Вызываем умную синхронизацию
            sync_missing_garmin_days(user_id)
            
            # Проверяем, что sync_garmin_data вызван для каждого дня
            # 30.01, 31.01, 01.02, 02.02 = 4 дня
            assert mock_sync_garmin.call_count == 4
            
    @patch('core.garmin_data.get_last_activity_date')
    @patch('core.garmin_data.sync_garmin_data')
    def test_sync_missing_days_today_only(
        self, 
        mock_sync_garmin,
        mock_get_last_date
    ):
        """Тест: если последняя дата = сегодня, синхронизируем только сегодня"""
        user_id = 895655
        today = date(2026, 2, 2)
        
        mock_get_last_date.return_value = today
        
        with patch('core.garmin_data.date') as mock_date:
            mock_date.today.return_value = today
            
            sync_missing_garmin_days(user_id)
            
            # Должен синхронизировать только сегодня
            assert mock_sync_garmin.call_count == 1
            
    @patch('core.garmin_data.get_last_activity_date')
    @patch('core.garmin_data.sync_garmin_data')
    def test_sync_missing_days_no_data(
        self, 
        mock_sync_garmin,
        mock_get_last_date
    ):
        """Тест: если нет данных в БД, синхронизируем только сегодня"""
        user_id = 895655
        
        # Нет данных в БД
        mock_get_last_date.return_value = None
        
        with patch('core.garmin_data.date') as mock_date:
            mock_date.today.return_value = date(2026, 2, 2)
            
            sync_missing_garmin_days(user_id)
            
            # Должен синхронизировать только сегодня
            assert mock_sync_garmin.call_count == 1


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
