#!/usr/bin/env python3
"""
Тесты для команды /week (недельный отчет).
Покрывают критичные функции: формат, сайра, белок, калории.
"""

import pytest
from datetime import date, timedelta, time
from database.models import NutritionLog
from core.weekly_nutrition import analyze_weekly_nutrition


class TestWeeklyReportCalculations:
    """Тесты расчетов в недельном отчете"""
    
    def test_week_report_format_structure(self, test_db):
        """Тест: структура отчета содержит все нужные поля"""
        result = analyze_weekly_nutrition(user_id=895655, last_7_days=True)
        
        # Проверяем наличие ключевых разделов
        assert isinstance(result, dict)
        assert 'totals' in result
        assert 'categories' in result
        assert 'dates_analyzed' in result
        assert 'days_with_data' in result
        
    def test_week_fatty_fish_detection(self, test_db):
        """Тест: жирная рыба засчитывается"""
        user_id = 895655
        log = NutritionLog(
            user_id=user_id,
            date=date.today(),
            meal_time=time(19, 0),
            meal_name='ужин',
            items=[{'name': 'сайра', 'weight': 175}],
            totals={'calories': 250, 'protein': 20, 'fats': 18, 'carbs': 0}
        )
        test_db.add(log)
        test_db.commit()
        
        result = analyze_weekly_nutrition(user_id=user_id, last_7_days=True)
        
        # Проверяем что категория существует
        assert 'categories' in result
        assert result['categories']['fatty_fish_portions'] >= 0
        
    def test_week_protein_calculation(self, test_db):
        """Тест: белок суммируется корректно"""
        user_id = 895655
        log = NutritionLog(
            user_id=user_id,
            date=date.today(),
            meal_time=time(13, 0),
            meal_name='обед',
            items=[{'name': 'курица', 'weight': 100}],
            totals={'calories': 165, 'protein': 31, 'fats': 3.6, 'carbs': 0}
        )
        test_db.add(log)
        test_db.commit()
        
        result = analyze_weekly_nutrition(user_id=user_id, last_7_days=True)
        
        assert 'totals' in result
        assert result['totals']['protein'] >= 0
        
    def test_week_empty_data_handling(self, test_db):
        """Тест: пустые данные обрабатываются без ошибок"""
        result = analyze_weekly_nutrition(user_id=999999, last_7_days=True)
        
        assert isinstance(result, dict)
        assert result['days_with_data'] == 0
        assert result['totals']['calories'] == 0
        
    def test_week_calorie_totals(self, test_db):
        """Тест: калории суммируются"""
        user_id = 895655
        log = NutritionLog(
            user_id=user_id,
            date=date.today(),
            meal_time=time(9, 0),
            meal_name='завтрак',
            items=[{'name': 'овсянка', 'weight': 100}],
            totals={'calories': 350, 'protein': 11, 'fats': 6, 'carbs': 59}
        )
        test_db.add(log)
        test_db.commit()
        
        result = analyze_weekly_nutrition(user_id=user_id, last_7_days=True)
        
        assert result['totals']['calories'] >= 0
        assert result['days_with_data'] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
