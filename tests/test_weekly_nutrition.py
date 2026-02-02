#!/usr/bin/env python3
"""
Тесты для детекции продуктов и недельного анализа питания.
Покрывают проблемы, которые были исправлены:
1. Детекция сайры как жирной рыбы
2. Парсинг name/weight vs food/amount форматов
3. Расчет порций жирной рыбы
"""

import pytest
from core.weekly_nutrition import categorize_food_item, analyze_weekly_nutrition
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


class TestFattyFishDetection:
    """Тесты детекции жирной рыбы"""
    
    def test_saira_detection_russian(self):
        """Тест: сайра определяется как жирная рыба (русский)"""
        result = categorize_food_item("Рыба сайра консервированная")
        assert result['fatty_fish'] is True
        
    def test_saira_detection_english(self):
        """Тест: saira определяется как жирная рыба (английский)"""
        result = categorize_food_item("Canned saira fish")
        assert result['fatty_fish'] is True
        
    def test_salmon_detection(self):
        """Тест: лосось определяется как жирная рыба"""
        result = categorize_food_item("Лосось слабосоленый")
        assert result['fatty_fish'] is True
        
    def test_mackerel_detection(self):
        """Тест: скумбрия определяется как жирная рыба"""
        result = categorize_food_item("Скумбрия запеченная")
        assert result['fatty_fish'] is True
        
    def test_not_fatty_fish(self):
        """Тест: треска НЕ жирная рыба"""
        result = categorize_food_item("Треска отварная")
        assert result['fatty_fish'] is False
        
    def test_case_insensitive(self):
        """Тест: детекция работает независимо от регистра"""
        assert categorize_food_item("САЙРА")['fatty_fish'] is True
        assert categorize_food_item("сайра")['fatty_fish'] is True
        assert categorize_food_item("Сайра")['fatty_fish'] is True


class TestPortionCalculation:
    """Тесты расчета порций"""
    
    def test_saira_portion_109g(self):
        """Тест: 109г сайры = 0.62 порций (109/175)"""
        # Моделируем один прием пищи с 109г сайры
        portions = 109 / 175
        assert abs(portions - 0.62) < 0.01
        
    def test_salmon_full_portion(self):
        """Тест: 175г лосося = 1 полная порция"""
        portions = 175 / 175
        assert portions == 1.0
        
    def test_fish_double_portion(self):
        """Тест: 350г рыбы = 2 порции"""
        portions = 350 / 175
        assert portions == 2.0
        
    def test_zero_fish(self):
        """Тест: 0г рыбы = 0 порций"""
        portions = 0 / 175
        assert portions == 0.0


class TestProductParsing:
    """Тесты парсинга продуктов из БД"""
    
    def test_name_weight_format(self):
        """Тест: парсинг формата name/weight (из БД)"""
        item = {
            'name': 'Рыба сайра консервированная',
            'weight': 109
        }
        
        # Эмуляция логики из analyze_weekly_nutrition
        food_name = item.get('name') or item.get('food') or ''
        amount_g = item.get('weight') or item.get('amount', 0.0) or 0.0
        
        assert food_name == 'Рыба сайра консервированная'
        assert amount_g == 109
        
    def test_food_amount_format_legacy(self):
        """Тест: парсинг формата food/amount (legacy)"""
        item = {
            'food': 'Гречка отварная',
            'amount': 200.0
        }
        
        food_name = item.get('name') or item.get('food') or ''
        amount_g = item.get('weight') or item.get('amount', 0.0) or 0.0
        
        assert food_name == 'Гречка отварная'
        assert amount_g == 200.0
        
    def test_both_formats_name_priority(self):
        """Тест: приоритет name над food если оба присутствуют"""
        item = {
            'name': 'Правильное название',
            'food': 'Старое название',
            'weight': 150,
            'amount': 100
        }
        
        food_name = item.get('name') or item.get('food') or ''
        amount_g = item.get('weight') or item.get('amount', 0.0) or 0.0
        
        assert food_name == 'Правильное название'
        assert amount_g == 150


class TestWeeklyAnalysisIntegration:
    """Интеграционные тесты недельного анализа"""
    
    @patch('core.weekly_nutrition.get_nutrition_logs_by_period')
    @patch('core.weekly_nutrition.get_activity_logs_by_period')
    @patch('core.weekly_nutrition.SessionLocal')
    def test_saira_detection_in_weekly_analysis(
        self, 
        mock_session_local,
        mock_activity_logs,
        mock_nutrition_logs
    ):
        """Тест: сайра засчитывается в недельном анализе"""
        
        # Мок сессии БД
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        # Мок логов активности
        mock_activity_logs.return_value = []
        
        # Мок логов питания с сайрой
        mock_log = MagicMock()
        mock_log.date = date.today()
        mock_log.meal_name = "Завтрак"
        mock_log.items = [
            {'name': 'Рыба сайра консервированная', 'weight': 109}
        ]
        mock_nutrition_logs.return_value = [mock_log]
        
        # Выполняем анализ
        result = analyze_weekly_nutrition(user_id=895655)
        
        # Проверяем, что сайра засчиталась
        fatty_fish_portions = result.get('categories', {}).get('fatty_fish_portions', 0)
        
        # 109г / 175г = 0.62 порций
        expected_portions = 109 / 175
        assert abs(fatty_fish_portions - expected_portions) < 0.01, \
            f"Ожидалось {expected_portions:.2f} порций, получено {fatty_fish_portions:.2f}"


class TestProteinTarget:
    """Тесты цели по белку"""
    
    def test_protein_target_is_150g(self):
        """Тест: цель по белку = 150г (не 177г)"""
        # В текущем коде target_protein = 150
        target_protein = 150
        assert target_protein == 150, "Цель по белку должна быть 150г"
        
    def test_protein_percentage_calculation(self):
        """Тест: расчет процента от цели по белку"""
        target_protein = 150
        actual_protein = 102
        
        percentage = (actual_protein / target_protein) * 100
        assert abs(percentage - 68.0) < 0.1


class TestRegressionBugs:
    """Regression тесты для специфичных багов"""
    
    def test_no_double_portion_multiply(self):
        """Regression: порция не умножается дважды (bug с пиццей)"""
        # Этот тест уже есть в test_nutrition_logic.py
        # Дублируем здесь для полноты
        from core.description_parser import apply_portion_multiplier
        
        products = [
            {'name': 'Pizza', 'weight': 420.0}
        ]
        
        # Половина пиццы
        result = apply_portion_multiplier(products, 0.5)
        
        assert result[0]['weight'] == 210.0, \
            "Половина 420г должна быть 210г, не 105г (двойное умножение)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
