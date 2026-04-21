import pytest
from datetime import date, time

from database.crud import (
    create_nutrition_log,
    get_nutrition_log,
    update_nutrition_item_weight,
    delete_nutrition_item,
    update_nutrition_meal_fields,
    find_meal_for_slot,
    get_recent_product_names,
)


@pytest.fixture
def sample_meal(test_db):
    return create_nutrition_log(
        db=test_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Курица", "weight_g": 100, "calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
            {"product": "Рис", "weight_g": 150, "calories": 195, "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2},
        ],
        totals={"calories": 360, "protein": 35.5, "fats": 5.1, "carbs": 42, "fiber": 2},
    )


def test_get_nutrition_log_returns_row(test_db, sample_meal):
    row = get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655)
    assert row is not None
    assert len(row.items) == 2
    assert row.totals["calories"] == 360


def test_get_nutrition_log_enforces_user_scope(test_db, sample_meal):
    assert get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=111) is None


def test_update_nutrition_item_weight_scales_proportionally(test_db, sample_meal):
    updated_item, new_totals = update_nutrition_item_weight(
        db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0, new_weight=200
    )
    # Function writes canonical "amount" and strips legacy "weight_g"
    assert updated_item["amount"] == 200
    assert "weight_g" not in updated_item
    assert updated_item["calories"] == pytest.approx(330, abs=1)
    assert updated_item["protein"] == pytest.approx(62, abs=0.1)
    assert new_totals["calories"] == pytest.approx(525, abs=1)


def test_update_item_weight_bad_idx(test_db, sample_meal):
    with pytest.raises(IndexError):
        update_nutrition_item_weight(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=9, new_weight=100)


def test_update_item_weight_wrong_user_raises(test_db, sample_meal):
    with pytest.raises(LookupError):
        update_nutrition_item_weight(db=test_db, meal_id=sample_meal.id, user_id=111, idx=0, new_weight=200)


def test_delete_nutrition_item_keeps_meal_if_others_remain(test_db, sample_meal):
    removed, new_totals = delete_nutrition_item(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0)
    assert removed["product"] == "Курица"
    row = get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655)
    assert row is not None
    assert len(row.items) == 1
    assert row.items[0]["product"] == "Рис"
    assert new_totals["calories"] == pytest.approx(195, abs=1)


def test_delete_last_item_removes_meal(test_db, sample_meal):
    delete_nutrition_item(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0)
    delete_nutrition_item(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0)
    assert get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655) is None


def test_update_meal_fields(test_db, sample_meal):
    updated = update_nutrition_meal_fields(
        db=test_db,
        meal_id=sample_meal.id,
        user_id=895655,
        meal_name="Поздний обед",
        meal_time=time(15, 30),
    )
    assert updated.meal_name == "Поздний обед"
    assert updated.meal_time == time(15, 30)


def test_update_meal_fields_partial(test_db, sample_meal):
    updated = update_nutrition_meal_fields(
        db=test_db,
        meal_id=sample_meal.id,
        user_id=895655,
        meal_name=None,
        meal_time=time(14, 0),
    )
    assert updated.meal_name == "Обед"
    assert updated.meal_time == time(14, 0)


def test_find_meal_for_slot_matches_by_name(test_db, sample_meal):
    row = find_meal_for_slot(test_db, user_id=895655, for_date=date(2026, 4, 17), slot="lunch")
    assert row is not None
    assert row.id == sample_meal.id


def test_find_meal_for_slot_none_if_missing(test_db, sample_meal):
    row = find_meal_for_slot(test_db, user_id=895655, for_date=date(2026, 4, 17), slot="dinner")
    assert row is None


def test_get_recent_product_names_aggregates(test_db):
    d1 = date(2026, 4, 10)
    d2 = date(2026, 4, 17)
    create_nutrition_log(
        test_db,
        user_id=895655,
        date=d1,
        meal_time=time(9, 0),
        meal_name="Завтрак",
        items=[{"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0}],
        totals={"calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0},
    )
    create_nutrition_log(
        test_db,
        user_id=895655,
        date=d2,
        meal_time=time(9, 0),
        meal_name="Завтрак",
        items=[
            {"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0},
            {"product": "Овсянка", "weight_g": 60, "calories": 240, "protein": 8, "fats": 5, "carbs": 42, "fiber": 6},
        ],
        totals={"calories": 250, "protein": 8, "fats": 5, "carbs": 44, "fiber": 6},
    )
    create_nutrition_log(
        test_db,
        user_id=111,
        date=d2,
        meal_time=time(9, 0),
        meal_name="Завтрак",
        items=[{"product": "Чай", "weight_g": 200, "calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}],
        totals={"calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0},
    )

    recents = get_recent_product_names(test_db, user_id=895655, limit=15, lookback_days=90)
    names = [r["name"] for r in recents]
    assert "Овсянка" in names
    assert "Кофе" in names
    assert "Чай" not in names
    for r in recents:
        assert "last_used" in r
        assert "per_100" in r
        for k in ("kcal", "p", "f", "c", "fib"):
            assert k in r["per_100"]
