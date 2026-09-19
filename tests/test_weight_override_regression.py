"""Regression tests for #408: явный вес из текста не должен перетираться дефолтной порцией."""

from core.food.nutrition import process_llm_food_data

DESC = "100 грамм гречневой каши с добавлением оливкового масла 1 чайная ложка и 2 вареных яйца"


def _llm(items):
    return {"type": "food", "data": {"dish_name": "Завтрак", "items": items}}


def test_explicit_grams_survive_declension_mismatch():
    items, totals = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Гречневая каша варёная",
                    "weight": 100,
                    "calories": 110,
                    "protein": 4,
                    "fats": 1,
                    "carbs": 21,
                }
            ]
        ),
        description=DESC,
    )
    assert items[0]["weight_g"] == 100
    assert items[0]["calories"] == 110


def test_default_override_scales_macros_when_no_user_weight():
    # LLM дал 50 г каши, вес в тексте не указан → дефолт 250 г, макросы масштабируются пропорционально
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Гречневая каша варёная",
                    "weight": 50,
                    "calories": 55,
                    "protein": 2,
                    "fats": 0.5,
                    "carbs": 10.5,
                }
            ]
        ),
        description="гречневая каша",
    )
    assert items[0]["weight_g"] == 250
    assert items[0]["calories"] == 275


def test_llm_weight_equal_to_user_weight_is_trusted():
    # Имя от LLM не пересекается с текстом даже по стемам, но вес совпал с явно указанным пользователем
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Крупа отварная",
                    "weight": 100,
                    "calories": 110,
                    "protein": 4,
                    "fats": 1,
                    "carbs": 21,
                }
            ]
        ),
        description="100 грамм гречки",
    )
    assert items[0]["weight_g"] == 100


def test_multi_item_weights_assigned_to_right_products():
    # Два продукта с разными весами: каждый item получает свой вес по стему, дефолт не трогает
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Гречневая каша варёная",
                    "weight": 100,
                    "calories": 110,
                    "protein": 4,
                    "fats": 1,
                    "carbs": 21,
                },
                {"name": "Творог 5%", "weight": 200, "calories": 242, "protein": 34, "fats": 10, "carbs": 6},
            ]
        ),
        description="100 грамм гречневой каши и 200 грамм творога",
    )
    by_name = {it["product"]: it for it in items}
    assert by_name["Гречневая каша варёная"]["weight_g"] == 100
    assert by_name["Творог 5%"]["weight_g"] == 200


def test_rice_and_salmon_weights_not_swapped_by_regex_safety_net():
    # Регрессия #449: до фикса regex-«страховка» пересекала границу продуктов на
    # "рис 180 г и лосось 90 г" (weight_patterns[0] матчил "180 г и лосось" целиком),
    # из-за чего лосось получал 180г вместо своих корректных 90г от LLM.
    items, _ = process_llm_food_data(
        _llm(
            [
                {"name": "Рис", "weight": 180, "calories": 200, "protein": 4, "fats": 0.5, "carbs": 44},
                {"name": "Лосось", "weight": 90, "calories": 180, "protein": 18, "fats": 12, "carbs": 0},
            ]
        ),
        description="рис 180 г и лосось 90 г",
    )
    by_name = {it["product"]: it for it in items}
    assert by_name["Рис"]["weight_g"] == 180
    assert by_name["Лосось"]["weight_g"] == 90, (
        f"Вес лосося перезаписан regex-страховкой: {by_name['Лосось']['weight_g']} (ожидали 90)"
    )


def test_ambiguous_equal_weights_do_not_bypass_default_override():
    # Два продукта по 50 г в тексте; LLM-имя третьего не совпадает ни с одним, но вес 50 совпадает
    # с обоими — совпадение неоднозначно, дефолтная порция для «каши» применяется (и макросы масштабируются)
    items, _ = process_llm_food_data(
        _llm([{"name": "Каша", "weight": 50, "calories": 55, "protein": 2, "fats": 0.5, "carbs": 10.5}]),
        description="50 г огурцов и 50 г сыра",
    )
    assert items[0]["weight_g"] == 250
    assert items[0]["calories"] == 275


# --- #470: суб-порция («ложка салата») не должна затираться дефолтной порцией ---


def test_spoon_of_salad_keeps_llm_weight():
    # Инцидент 19.09.2026: «ложка салата оливье» → дефолт по ключу «салат» (200 г)
    # перетирал корректные 40 г от LLM и масштабировал КБЖУ ×5 (815 ккал вместо ~270).
    items, totals = process_llm_food_data(
        _llm(
            [
                {"name": "Сосиска", "weight": 50, "calories": 135, "protein": 5, "fats": 12, "carbs": 1, "fiber": 0},
                {
                    "name": "Салат сельдь под шубой",
                    "weight": 40,
                    "calories": 80,
                    "protein": 1.2,
                    "fats": 6,
                    "carbs": 3.2,
                    "fiber": 0.6,
                },
                {
                    "name": "Салат оливье",
                    "weight": 40,
                    "calories": 56,
                    "protein": 2,
                    "fats": 3.6,
                    "carbs": 3.6,
                    "fiber": 0.4,
                },
            ]
        ),
        description="1 сосиска, ложка салата сельд под шубой, ложка салата оливье",
    )
    by_name = {it["product"]: it for it in items}
    assert by_name["Салат сельдь под шубой"]["weight_g"] == 40
    assert by_name["Салат сельдь под шубой"]["calories"] == 80
    assert by_name["Салат оливье"]["weight_g"] == 40
    assert by_name["Салат оливье"]["calories"] == 56
    assert totals["calories"] < 300, f"итог {totals['calories']} ккал — ложки снова посчитаны как порции"


def test_piece_marker_keeps_llm_weight():
    # «кусочек пиццы»: дефолт «пицца» = 100 г, LLM дал 40 г — доверяем LLM
    items, _ = process_llm_food_data(
        _llm([{"name": "Пицца", "weight": 40, "calories": 100, "protein": 4, "fats": 4, "carbs": 12}]),
        description="кусочек пиццы",
    )
    assert items[0]["weight_g"] == 40
    assert items[0]["calories"] == 100


def test_subportion_in_other_segment_does_not_block_default():
    # Маркер «ложка» относится к маслу, а не к каше — для каши дефолт 250 г работает как раньше
    items, _ = process_llm_food_data(
        _llm(
            [
                {"name": "Оливковое масло", "weight": 15, "calories": 133, "protein": 0, "fats": 15, "carbs": 0},
                {
                    "name": "Гречневая каша варёная",
                    "weight": 50,
                    "calories": 55,
                    "protein": 2,
                    "fats": 0.5,
                    "carbs": 10.5,
                },
            ]
        ),
        description="ложка оливкового масла, гречневая каша",
    )
    by_name = {it["product"]: it for it in items}
    assert by_name["Оливковое масло"]["weight_g"] == 15
    assert by_name["Гречневая каша варёная"]["weight_g"] == 250
    assert by_name["Гречневая каша варёная"]["calories"] == 275


def test_default_override_scales_fiber_too():
    # Вес ×5 → клетчатка тоже ×5 (раньше оставалась от исходной порции)
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Гречневая каша варёная",
                    "weight": 50,
                    "calories": 55,
                    "protein": 2,
                    "fats": 0.5,
                    "carbs": 10.5,
                    "fiber": 1.0,
                }
            ]
        ),
        description="гречневая каша",
    )
    assert items[0]["weight_g"] == 250
    assert items[0]["fiber"] == 5.0


def test_default_override_marks_weight_source():
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Гречневая каша варёная",
                    "weight": 50,
                    "calories": 55,
                    "protein": 2,
                    "fats": 0.5,
                    "carbs": 10.5,
                }
            ]
        ),
        description="гречневая каша",
    )
    assert items[0]["weight_source"] == "default_portion"


def test_mentions_subportion_matches_declensions_and_scopes_segments():
    from core.food.nutrition import mentions_subportion

    assert mentions_subportion("ложка салата оливье", "Салат оливье")
    assert mentions_subportion("пара ложек оливье", "Оливье")
    assert mentions_subportion("чуть-чуть каши", "Каша гречневая")
    assert mentions_subportion("кусочек пиццы", "Пицца")
    # Без маркера — дефолтная порция работает как раньше
    assert not mentions_subportion("салат оливье", "Салат оливье")
    assert not mentions_subportion("гречневая каша", "Гречневая каша варёная")
    # Маркер в чужом сегменте не распространяется на другой продукт
    assert not mentions_subportion("2 столовые ложки варенья, творог 150 г", "Творог 5%")


def test_spoons_of_porridge_keep_llm_weight():
    items, _ = process_llm_food_data(
        _llm([{"name": "Каша гречневая", "weight": 60, "calories": 66, "protein": 2.4, "fats": 0.6, "carbs": 12.6}]),
        description="пара ложек каши",
    )
    assert items[0]["weight_g"] == 60
    assert items[0]["calories"] == 66
