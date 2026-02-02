#!/usr/bin/env python3
"""
Тесты для функционала витаминов.
Покрывают: сохранение, время приема, логирование на вчера.
"""

import pytest
from datetime import datetime, date, timedelta
from database.models import SupplementLog
from database.crud import create_supplement_log


class TestVitaminLogging:
    """Тесты логирования витаминов"""
    
    def test_vitamin_logging_basic(self, test_db):
        """Тест: базовое сохранение витамина"""
        user_id = 895655
        
        # Сохраняем витамин
        create_supplement_log(
            test_db,
            user_id=user_id,
            date=date.today(),
            time=datetime.now().time(),
            supplement_name='Магний',
            dosage=None
        )
        
        # Проверяем что запись создана
        logs = test_db.query(SupplementLog).filter(
            SupplementLog.user_id == user_id,
            SupplementLog.supplement_name == 'Магний'
        ).all()
        
        assert len(logs) >= 1
        
    def test_vitamin_variations(self, test_db):
        """Тест: различные варианты написания"""
        user_id = 895655
        
        # Разные варианты
        variants = ['Омега', 'Витамин Д', 'Цинк']
        
        for var in variants:
            create_supplement_log(
                test_db,
                user_id=user_id,
                date=date.today(),
                time=datetime.now().time(),
                supplement_name=var,
                dosage=None
            )
        
        # Проверяем что все сохранились
        logs = test_db.query(SupplementLog).filter(
            SupplementLog.user_id == user_id
        ).all()
        
        assert len(logs) >= len(variants)
        
    def test_vitamin_yesterday_logging(self, test_db):
        """Тест: логирование витаминов на вчера"""
        user_id = 895655
        yesterday = date.today() - timedelta(days=1)
        
        create_supplement_log(
            test_db,
            user_id=user_id,
            date=yesterday,
            time=datetime.now().time(),
            supplement_name='Цинк',
            dosage=None
        )
        
        # Проверяем дату
        log = test_db.query(SupplementLog).filter(
            SupplementLog.user_id == user_id,
            SupplementLog.supplement_name == 'Цинк'
        ).order_by(SupplementLog.created_at.desc()).first()
        
        assert log is not None
        assert log.date == yesterday


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
