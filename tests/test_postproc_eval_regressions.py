"""Постобработка не должна портить корректный ответ LLM (eval 18.10.2026, PR #620).

`rescore.py --postproc` на golden_v3: Sonnet 5 89% → 85%, карточки 100% → 73%.
Три причины:
  1. Дефолтная порция из справочника перекрывала вес LLM у позиций, которых
     пользователь в тексте не называл (фото карточки): «Паста из трав…» 30 г → 150 г, ×5.
  2. Маркер «без сахара» делал из мороженого «напиток без калорий» → итог 0 ккал.
  3. Явный вес «бургер с фри 100г» навязывался бургеру, хотя LLM уже отдал эти 100 г фри.
"""

from core.food.description_parser import is_zero_calorie_drink
from core.food.nutrition import process_llm_food_data


def _llm(items, **extra):
    total = {k: sum(float(it.get(k) or 0) for it in items) for k in ("calories", "protein", "fats", "carbs")}
    return {"type": "food", "data": {"dish_name": "x", "items": items, "total_nutrition": total, **extra}}


def _item(name, weight, calories, protein=1.0, fats=1.0, carbs=1.0):
    return {"name": name, "weight": weight, "calories": calories, "protein": protein, "fats": fats, "carbs": carbs}


# --- 1. дефолтная порция ---------------------------------------------------


def test_card_side_item_keeps_llm_weight_without_caption():
    llm = _llm(
        [
            _item("Тайский рис", 140, 180),
            _item("Креветки су-вид", 100, 95),
            _item("Паста из трав с чесноком и апельсиновый микс с маком", 30, 233, protein=None),
        ]
    )
    items, totals = process_llm_food_data(llm, "")
    pasta = items[2]
    assert pasta["weight_g"] == 30
    assert pasta["calories"] == 233
    assert totals["calories"] == 508


def test_photo_items_not_named_in_caption_keep_llm_weight():
    # «Мандариновый соус» → справочник «мандарин» 80 г; «Перец гриль» → 150 г
    llm = _llm([_item("Мандариновый соус с горчицей", 30, 60), _item("Перец гриль", 45, 20)])
    items, _ = process_llm_food_data(llm, "обед из доставки")
    assert [it["weight_g"] for it in items] == [30, 45]
    assert [it["calories"] for it in items] == [60, 20]


def test_default_portion_still_applies_to_dish_named_in_text():
    # Поведение #408 сохраняется: пользователь назвал блюдо без граммов
    llm = _llm([_item("Гречневая каша варёная", 50, 55)])
    items, _ = process_llm_food_data(llm, "гречневая каша")
    assert items[0]["weight_g"] == 250
    assert items[0]["calories"] == 275


def test_implausible_llm_weight_gets_default_even_without_caption():
    # 2 г пиццы — галлюцинация, а не доля: справочник нужен и без подписи
    llm = _llm([_item("Пицца", 2, 5)])
    items, _ = process_llm_food_data(llm, "")
    assert items[0]["weight_g"] > 2
    assert items[0]["weight_source"] == "default_portion"


# --- 2. «без сахара» -------------------------------------------------------


def test_sugar_free_marker_alone_is_not_a_zero_drink():
    assert not is_zero_calorie_drink("Мороженое протеиновое без сахара")
    assert not is_zero_calorie_drink("Шоколад без сахара")
    assert not is_zero_calorie_drink("Батончик лайт")


def test_zero_drinks_still_detected():
    assert is_zero_calorie_drink("Coca-Cola Zero")
    assert is_zero_calorie_drink("Кола без сахара")
    assert is_zero_calorie_drink("Напиток газированный без сахара")
    assert is_zero_calorie_drink("Пепси лайт")
    assert is_zero_calorie_drink("Энергетик sugar free")


def test_sugar_free_ice_cream_with_label_keeps_calories():
    item = _item("Мороженое протеиновое без сахара", 150, 403, protein=34, fats=14, carbs=32)
    llm = _llm(
        [item],
        dish_name="Мороженое протеиновое Ореховое без сахара",
        product_label={
            "name": "Мороженое протеиновое без сахара",
            "calories_per_100g": 268.5,
            "protein_per_100g": 22.5,
            "fats_per_100g": 9,
            "carbs_per_100g": 21,
            "portion_g": 150,
        },
    )
    items, totals = process_llm_food_data(llm, "")
    assert items[0]["calories"] > 0
    assert totals["calories"] > 0


# --- 3. явный вес, уже отданный другой позиции ---------------------------


BURGER_TEXT = "ел на обед бургер с фри 100г и соусом айоли, Гаспачо с двумя тостами с сыром"


def test_explicit_weight_already_held_by_other_item_is_not_reassigned():
    llm = _llm(
        [
            _item("Бургер", 250, 600, protein=25, fats=35, carbs=45),
            _item("Картофель фри", 100, 280, protein=3, fats=14, carbs=36),
            _item("Соус айоли", 20, 130, protein=0.5, fats=14, carbs=1),
            _item("Гаспачо", 250, 100, protein=2, fats=5, carbs=10),
        ]
    )
    items, totals = process_llm_food_data(llm, BURGER_TEXT)
    burger = items[0]
    assert burger["weight_g"] == 250
    assert burger["calories"] == 600
    assert totals["calories"] == 1110


def test_explicit_weight_still_overrides_when_no_other_item_holds_it():
    # «бургер 300г», LLM дал 250 — вес пользователя побеждает (поведение не меняется)
    llm = _llm([_item("Бургер", 250, 600), _item("Картофель фри", 120, 340)])
    items, _ = process_llm_food_data(llm, "бургер 300г и картошка фри")
    assert items[0]["weight_g"] == 300
    assert items[0]["calories"] == 720
