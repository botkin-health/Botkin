import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from datetime import time

from webhook.nutrition_slots import (
    slot_from_time,
    slot_from_meal,
    slot_center_time,
    slot_label_ru,
    SLOTS,
)


def test_slot_from_time_boundaries():
    assert slot_from_time(time(6, 0)) == "breakfast"
    assert slot_from_time(time(10, 59)) == "breakfast"
    assert slot_from_time(time(11, 0)) == "lunch"
    assert slot_from_time(time(14, 59)) == "lunch"
    assert slot_from_time(time(15, 0)) == "snack"
    assert slot_from_time(time(17, 59)) == "snack"
    assert slot_from_time(time(18, 0)) == "dinner"
    assert slot_from_time(time(23, 59)) == "dinner"
    assert slot_from_time(time(0, 0)) == "dinner"
    assert slot_from_time(time(5, 59)) == "dinner"


def test_slot_from_meal_name_priority():
    # Name match wins over time
    assert slot_from_meal("Завтрак", time(14, 0)) == "breakfast"
    assert slot_from_meal("breakfast", time(14, 0)) == "breakfast"
    assert slot_from_meal("🌅 Завтрак дома", time(14, 0)) == "breakfast"
    assert slot_from_meal("Обед", time(8, 0)) == "lunch"
    assert slot_from_meal("Перекус", time(21, 0)) == "snack"
    assert slot_from_meal("Ужин", time(8, 0)) == "dinner"


def test_slot_from_meal_falls_back_to_time():
    assert slot_from_meal("", time(13, 0)) == "lunch"
    assert slot_from_meal(None, time(13, 0)) == "lunch"
    assert slot_from_meal("12:30", time(12, 30)) == "lunch"
    assert slot_from_meal("Что-то непонятное", time(10, 0)) == "breakfast"


def test_slot_from_meal_no_time():
    assert slot_from_meal(None, None) == "breakfast"
    assert slot_from_meal("", None) == "breakfast"


def test_slot_center_time():
    assert slot_center_time("breakfast") == time(9, 0)
    assert slot_center_time("lunch") == time(13, 0)
    assert slot_center_time("snack") == time(16, 0)
    assert slot_center_time("dinner") == time(19, 0)


def test_slot_label_ru():
    assert slot_label_ru("breakfast") == "Завтрак"
    assert slot_label_ru("lunch") == "Обед"
    assert slot_label_ru("snack") == "Перекус"
    assert slot_label_ru("dinner") == "Ужин"


def test_slots_order():
    assert SLOTS == ("breakfast", "lunch", "snack", "dinner")
