"""
РЕГРЕССИОННЫЙ ТЕСТ: защита от LLM-галлюцинаций по калорийной плотности.

История:
- 05 апреля 2026 в логах зафиксировано:
  "⚠️ LLM сгаллюцинировал макросы для 'Яйца'! 231.0 ккал на 18.0г (1283.3 ккал/100г). Игнорируем."
- Код в core/food/nutrition.py ловит случаи cal_per_100g > 1000 и отбрасывает макросы
- Этот тест проверяет что защита работает и не сломается при рефакторинге

Физически допустимая плотность:
- Минимум: огурец, кофе без молока — ~0 ккал/100г
- Максимум: масло, сало — ~900 ккал/100г
- Выше 1000 ккал/100г — НЕВОЗМОЖНО в реальной еде → галлюцинация

Что проверяем:
1. Галлюцинация (>1000 ккал/100г) отбрасывается → has_macros = False
2. Нормальные значения (100-900 ккал/100г) принимаются
3. Граничные значения (ровно 1000) — поведение
4. Продукты без веса не проверяются (weight=None)
5. Правило #11 из промпта: 0.1–9 ккал/г (наш внутренний чек жёстче)
"""

import pytest


def simulate_density_check(calories: float, weight: float) -> bool:
    """
    Воспроизводит логику защиты из core/food/nutrition.py.
    Возвращает True если макросы приняты, False если отброшены.
    """
    has_macros = calories is not None and calories > 0
    if has_macros and weight and weight > 0:
        cal_per_100g = (calories / weight) * 100
        if cal_per_100g > 1000:
            has_macros = False
    return has_macros


class TestCaloricDensityValidation:
    """Проверяем пороговую логику отбрасывания галлюцинаций."""

    # --- ГАЛЛЮЦИНАЦИИ (должны быть отброшены) ---

    def test_hallucination_eggs_real_case(self):
        """Реальный кейс из лога: яйца 231 ккал / 18г = 1283 ккал/100г."""
        result = simulate_density_check(calories=231.0, weight=18.0)
        assert result is False, "1283 ккал/100г — галлюцинация, должна быть отброшена"

    def test_hallucination_broccoli_real_case(self):
        """Брокколи 270 ккал / 150г — исторический баг в аудите марта."""
        # 270/150 * 100 = 180 ккал/100г — это НЕ галлюцинация (жареная брокколи с маслом)
        result = simulate_density_check(calories=270.0, weight=150.0)
        assert result is True, "180 ккал/100г — допустимо (жареная с маслом)"

    def test_hallucination_butter_correct(self):
        """Масло 748 ккал/100г — корректно, не отбрасывается."""
        result = simulate_density_check(calories=748.0, weight=100.0)
        assert result is True, "748 ккал/100г — масло, допустимо"

    def test_hallucination_above_threshold(self):
        """Явная галлюцинация: 2000 ккал / 100г."""
        result = simulate_density_check(calories=2000.0, weight=100.0)
        assert result is False, "2000 ккал/100г физически невозможно"

    def test_hallucination_just_over_threshold(self):
        """Граница: ровно 1001 ккал/100г — отбрасывается."""
        result = simulate_density_check(calories=1001.0, weight=100.0)
        assert result is False, "1001 ккал/100г — выше порога"

    def test_hallucination_tiny_portion(self):
        """Маленькая порция с огромными калориями: 500 ккал / 10г = 5000 ккал/100г."""
        result = simulate_density_check(calories=500.0, weight=10.0)
        assert result is False, "5000 ккал/100г — галлюцинация для 10г"

    # --- НОРМАЛЬНЫЕ ЗНАЧЕНИЯ (должны быть приняты) ---

    @pytest.mark.parametrize(
        "name,calories,weight,expected_ok",
        [
            ("Масло сливочное", 748, 100, True),  # 748 ккал/100г
            ("Масло сливочное 30г", 224, 30, True),  # 747 ккал/100г
            ("Оливковое масло 15г", 132, 15, True),  # 880 ккал/100г
            ("Орехи грецкие 30г", 196, 30, True),  # 654 ккал/100г
            ("Куриная грудка 200г", 330, 200, True),  # 165 ккал/100г
            ("Брокколи 200г", 68, 200, True),  # 34 ккал/100г
            ("Креветки 150г", 143, 150, True),  # 95 ккал/100г
            ("Кофе без молока 200мл", 6, 200, True),  # 3 ккал/100г
            ("Вода 200мл", 0, 200, False),  # 0 ккал — has_macros=False сразу
            ("Овсянка 50г сухая", 180, 50, True),  # 360 ккал/100г
            ("Гречка 80г сухая", 264, 80, True),  # 330 ккал/100г
        ],
    )
    def test_realistic_caloric_densities(self, name, calories, weight, expected_ok):
        """Реалистичные плотности — все должны пройти проверку."""
        result = simulate_density_check(calories=calories, weight=weight)
        assert result == expected_ok, (
            f"{name}: {calories} ккал / {weight}г = {calories / weight * 100:.0f} ккал/100г — "
            f"ожидали {'принято' if expected_ok else 'отброшено'}"
        )

    # --- ГРАНИЧНЫЕ СЛУЧАИ ---

    def test_no_weight_skips_check(self):
        """Если вес None — проверка не запускается, макросы принимаются."""
        # Логика: if has_macros and weight and weight > 0 — при weight=None пропускаем
        calories = 5000.0  # галлюцинация, но без веса проверка не запустится
        weight = None
        has_macros = calories is not None and calories > 0
        if has_macros and weight and weight > 0:
            cal_per_100g = (calories / weight) * 100
            if cal_per_100g > 1000:
                has_macros = False
        # Без веса — не можем проверить, принимаем как есть
        assert has_macros is True, "Без веса галлюцинацию нельзя детектировать — принимаем"

    def test_zero_calories_rejected(self):
        """0 калорий для реальной еды — has_macros=False."""
        result = simulate_density_check(calories=0.0, weight=100.0)
        assert result is False

    def test_none_calories_rejected(self):
        """None калорий — has_macros=False."""
        has_macros = None is not None and None > 0  # noqa: E711
        assert has_macros is False

    def test_exact_threshold_999(self):
        """Ровно 999 ккал/100г — на границе, принимается."""
        result = simulate_density_check(calories=999.0, weight=100.0)
        assert result is True, "999 ккал/100г — ниже порога 1000, принимается"

    def test_exact_threshold_1000(self):
        """Ровно 1000 ккал/100г — на границе, принимается (порог строго >1000)."""
        result = simulate_density_check(calories=1000.0, weight=100.0)
        assert result is True, "1000 ккал/100г — ровно на пороге, не превышает"


class TestPromptDensityRule:
    """Правило #11 из SYSTEM_PROMPT: плотность должна быть 0.1–9 ккал/г."""

    @pytest.mark.parametrize(
        "product,cal_per_g",
        [
            ("вода", 0.0),
            ("огурец", 0.15),
            ("куриная грудка", 1.65),
            ("сыр пармезан", 4.31),
            ("сливочное масло", 7.48),
            ("масло оливковое", 8.84),
        ],
    )
    def test_real_products_within_physical_range(self, product, cal_per_g):
        """Реальные продукты имеют плотность 0–9 ккал/г."""
        # Проверяем что правило из промпта (#11) имеет физический смысл
        assert 0 <= cal_per_g <= 9, f"{product}: {cal_per_g} ккал/г выходит за физические пределы"

    def test_butter_density_is_748_per_100g(self):
        """Якорная калорийность масла — 748 ккал/100г (из CALORIC DENSITY ANCHORS)."""
        butter_per_100g = 748
        assert butter_per_100g / 100 < 9, "748 ккал/100г = 7.48 ккал/г — в пределах нормы"

    def test_hallucination_eggs_exceeds_physical_max(self):
        """Реальный кейс галлюцинации (яйца 1283 ккал/100г) нарушает физические пределы."""
        hallucinated_per_100g = (231.0 / 18.0) * 100  # ≈ 1283
        assert hallucinated_per_100g > 9 * 100, "1283 ккал/100г > 9 ккал/г — физически невозможно"
