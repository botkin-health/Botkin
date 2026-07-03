"""MealStateData — typed schema для meal-flow ветки UserState.data.

Заводится как follow-up к #256/#258: dict-литералы с ключами meal_items/
meal_totals/photo_paths собирались вручную в 4+ местах в photo.py/text.py,
опечатка в имени ключа (photo_path вместо photo_paths, #256) молча теряла
данные вместо ошибки. MealStateData (extra="forbid") ловит такую опечатку
в момент создания состояния — не в save_meal_to_db() при чтении.
"""

import pytest
from pydantic import ValidationError

from services.state_helpers import build_meal_state_data
from services.state_models import MealStateData


def test_rejects_unknown_field_photo_path_typo():
    with pytest.raises(ValidationError):
        MealStateData(
            meal_items=[{"product": "Банан"}],
            meal_totals={"calories": 100},
            photo_path=["/tmp/x.jpg"],  # опечатка: должно быть photo_paths
        )


def test_requires_meal_items():
    with pytest.raises(ValidationError):
        MealStateData(meal_totals={"calories": 100})


def test_requires_meal_totals():
    with pytest.raises(ValidationError):
        MealStateData(meal_items=[{"product": "Банан"}])


def test_accepts_valid_minimal_data():
    data = MealStateData(meal_items=[{"product": "Банан"}], meal_totals={"calories": 100})
    assert data.photo_paths == []
    assert data.meal_name is None


def test_build_meal_state_data_returns_plain_dict_for_user_state():
    result = build_meal_state_data(
        meal_items=[{"product": "Банан"}],
        meal_totals={"calories": 100},
        photo_paths=["/tmp/x.jpg"],
        meal_name="Завтрак",
    )
    assert result == {
        "meal_items": [{"product": "Банан"}],
        "meal_totals": {"calories": 100.0},
        "photo_paths": ["/tmp/x.jpg"],
        "meal_name": "Завтрак",
    }


def test_build_meal_state_data_raises_on_typo():
    with pytest.raises(ValidationError):
        build_meal_state_data(
            meal_items=[{"product": "Банан"}],
            meal_totals={"calories": 100},
            photo_path=["/tmp/x.jpg"],  # опечатка
        )
