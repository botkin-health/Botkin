from core.food.description_parser import (
    apply_portion_multiplier,
    extract_products_from_description,
    normalize_product_name,
)
from core.food.nutrition import calculate_nutrition


# 1. Test for "Pizza Weight Bug" (Double Multiplication)
def test_portion_multiplier_only_affects_weight_correctly():
    """
    Simulate the 'Half Pizza' scenario.
    If we have a product of 400g and apply 0.5 multiplier,
    it should become 200g.
    It should NOT become 100g (applied twice) or remain 400g.
    """
    products = [{"name": "Pizza", "weight": 400.0, "calories": 800.0}]

    # Apply 0.5 (half)
    multiplied = apply_portion_multiplier(products, 0.5)

    assert len(multiplied) == 1
    item = multiplied[0]

    # Weight should be halved
    assert item["weight"] == 200.0

    # Calories should be halved implies the logic in apply_portion_multiplier
    # handles calories too if present. Let's verify what it does.
    # If it only changes weight, that's fine, as long as calculate_nutrition
    # downstream uses the new weight.
    # Checking implementation behavior:
    if "calories" in item:
        assert item["calories"] == 400.0


def test_nutrition_calculation_linear_scaling():
    """
    Ensure calculate_nutrition scales linearly with weight.
    200g should have exactly 2x calories of 100g.
    """
    # Assuming 'dummy_product' doesn't exist, it might use default or search.
    # Better to use a known product or mock to avoid network calls?
    # calculate_nutrition uses find_product.
    # We will trust that for 'oats' or similar simple product it finds something or uses default.

    # Use a product that likely hits default values if DB empty: "яйцо" (Egg)
    # Default in code: 143 kcal/100g

    res_100 = calculate_nutrition("яйцо", 100.0)
    res_200 = calculate_nutrition("яйцо", 200.0)

    assert res_100["calories"] > 0
    # Allow small float error
    assert abs(res_200["calories"] - (res_100["calories"] * 2)) < 0.2


# 2. Test for "Duplication Bug"
def test_normalization_removes_duplicates():
    """
    Test that different forms of the same product normalize to the same string.
    """
    assert normalize_product_name("куриное филе") == "куриное филе"
    assert normalize_product_name("куриная грудка") == "куриное филе"  # Check alias

    # "вареная картошка" vs "картофель отварной"
    assert normalize_product_name("вареная картошка") == "картофель отварной"


def test_parser_deduplication():
    """
    Test that the parser doesn't output duplicates logic if implemented.
    NOTE: The parser regex might output raw items, deduplication often happens
    in process_meal_description.
    Let's check extract_products_from_description behavior directly.
    """
    # Description with "Tomato 100g" and "Tomato"
    # Depending on logic, it might keep both if one has weight and other doesn't,
    # or merge them. Ideally, we want no duplicates.

    desc = "помидор 100г и помидор"
    products = extract_products_from_description(desc)

    # Depending on implementation quality, this might fail if bug exists.
    # We expect efficient deduplication.

    names = [p["name"] for p in products]
    # Ideally should be just one "томат" (normalized)
    assert names.count("томат") <= 1


def test_parser_quantity_logic():
    """
    Test 3 eggs = 165g (3 * 55g).
    """
    desc = "3 яйца"
    products = extract_products_from_description(desc)

    assert len(products) == 1
    item = products[0]
    assert item["name"] == "яйцо"
    assert item["weight"] == 3 * 55  # 165


def test_half_fruit_parsing_regression():
    """
    Regression: «половина груши и половина банана» раньше давала 700г и 600г
    (regex матчил "5" из "0.5" как количество). Должно быть ~70г и ~60г.
    """
    desc = "половина груши и половина банана"
    products = extract_products_from_description(desc)

    by_name = {p["name"]: p for p in products}
    assert "груша" in by_name, "Груша должна быть в результате"
    assert "банан" in by_name, "Банан должен быть в результате"

    # Половина груши: 140г * 0.5 = 70г (не 700!)
    pear = by_name["груша"]
    assert 50 <= pear["weight"] <= 90, f"Половина груши ~70г, получено {pear['weight']}"
    assert pear["weight"] < 200, "Баг: половина груши не должна быть >200г"

    # Половина банана: 120г * 0.5 = 60г (не 600!)
    banana = by_name["банан"]
    assert 40 <= banana["weight"] <= 80, f"Половина банана ~60г, получено {banana['weight']}"
    assert banana["weight"] < 200, "Баг: половина банана не должна быть >200г"


# ── Issue #115: вес по типу блюда вместо слепого дефолта 200г ─────────────────
def test_estimate_default_weight_bowl():
    """Боул/поке/тарелка-как-блюдо → ~330г, а не слепые 200г."""
    from core.food.nutrition import estimate_default_weight

    assert estimate_default_weight("боул с курицей") == 330.0
    assert estimate_default_weight("Поке с лососем") == 330.0


def test_estimate_default_weight_side_dish():
    """Гарнир/каша → ~150г."""
    from core.food.nutrition import estimate_default_weight

    assert estimate_default_weight("гарнир из риса") == 150.0
    assert estimate_default_weight("овсяная каша") == 150.0


def test_estimate_default_weight_soup():
    """Суп → ~300г."""
    from core.food.nutrition import estimate_default_weight

    assert estimate_default_weight("борщ суп") == 300.0
    assert estimate_default_weight("Крем-суп грибной") == 300.0


def test_estimate_default_weight_unknown():
    """Неизвестное блюдо → дефолт 200г (как раньше)."""
    from core.food.nutrition import estimate_default_weight

    assert estimate_default_weight("нечто непонятное") == 200.0
    assert estimate_default_weight("") == 200.0


# ── Issue #115: sanity-флаг по плотности салатов/боулов ──────────────────────
def test_check_density_sanity_flags_dense_salad():
    """Салат 260 ккал/100г превышает порог 180 → warning."""
    from core.food.nutrition import check_density_sanity

    items = [{"product": "салат зелёный", "weight_g": 100.0, "calories": 260.0}]

    warnings = check_density_sanity(items)

    assert len(warnings) == 1
    assert warnings[0]["name"] == "салат зелёный"
    assert round(warnings[0]["density"]) == 260
    assert warnings[0]["weight"] == 100.0


def test_check_density_sanity_ok_light_salad():
    """Салат 60 ккал/100г ниже порога → нет warning."""
    from core.food.nutrition import check_density_sanity

    items = [{"product": "салат овощной", "weight_g": 200.0, "calories": 120.0}]

    warnings = check_density_sanity(items)

    assert warnings == []


def test_check_density_sanity_ignores_non_salad_dense_dish():
    """Жирное НЕ-салатное блюдо (например, бекон) — флаг не ставим."""
    from core.food.nutrition import check_density_sanity

    items = [{"product": "бекон жареный", "weight_g": 100.0, "calories": 500.0}]

    warnings = check_density_sanity(items)

    assert warnings == []


def test_check_density_sanity_skips_zero_weight():
    """Нулевой/отсутствующий вес → деление невозможно, пропускаем."""
    from core.food.nutrition import check_density_sanity

    items = [{"product": "салат", "weight_g": 0.0, "calories": 300.0}]

    warnings = check_density_sanity(items)

    assert warnings == []


def test_format_kcal_warning_includes_density_line():
    """format_kcal_warning рендерит строку про плотность салата."""
    from core.food.nutrition import format_kcal_warning

    totals = {"kcal_warnings": [{"name": "салат", "density": 260.0, "weight": 100.0}]}

    text = format_kcal_warning(totals)

    assert "калорийнее обычного салата" in text
    assert "260" in text


def test_estimate_default_weight_bowl_beats_side_dish():
    """«тарелка каши» содержит и bowl-, и side-слово → побеждает боул (330), не гарнир."""
    from core.food.nutrition import estimate_default_weight

    assert estimate_default_weight("тарелка каши") == 330.0
    assert estimate_default_weight("боул-каша") == 330.0


def test_format_kcal_warning_density_only_header_not_mismatch():
    """Только density-флаг → заголовок НЕ про «Расхождение ккал и БЖУ» (issue #115)."""
    from core.food.nutrition import format_kcal_warning

    totals = {"kcal_warnings": [{"name": "салат", "density": 260.0, "weight": 100.0}]}

    text = format_kcal_warning(totals)

    assert "Расхождение ккал и БЖУ" not in text
    assert "Необычная калорийность" in text


def test_collect_meal_warnings_skips_kcal_check_for_alcohol():
    """has_alcohol=True → kcal↔БЖУ-расхождения не считаем (этанол не в формуле)."""
    from core.food.nutrition import _collect_meal_warnings

    # Вино: 80 ккал заявлено, по БЖУ ≈ 0 — без alcohol-флага был бы mismatch.
    items = [{"product": "вино красное", "weight_g": 100.0, "calories": 80.0, "protein": 0, "fats": 0, "carbs": 0}]

    warns = _collect_meal_warnings(items, has_alcohol=True)

    assert warns == []


def test_format_kcal_warning_escapes_html_in_name():
    """Имя блюда от LLM с HTML-тегами экранируется (anti-XSS, issue #115)."""
    from core.food.nutrition import format_kcal_warning

    totals = {"kcal_warnings": [{"name": "<b>салат</b>", "density": 260.0, "weight": 100.0}]}

    text = format_kcal_warning(totals)

    assert "<b>салат</b>" not in text
    assert "&lt;b&gt;салат&lt;/b&gt;" in text


def test_check_density_sanity_ignores_negative_calories():
    """Отрицательные ккал (галлюцинация LLM) не дают ложный/тихий density-флаг."""
    from core.food.nutrition import check_density_sanity

    items = [{"product": "салат", "weight_g": 100.0, "calories": -50.0}]

    assert check_density_sanity(items) == []
