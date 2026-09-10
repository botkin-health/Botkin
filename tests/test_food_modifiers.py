import pytest

from core.food.modifiers import apply_modifiers, describe_applied, parse_modifiers

ITEMS = [
    {"product": "Куриные стрипсы", "weight_g": 150, "calories": 250, "protein": 30, "fats": 12, "carbs": 5, "fiber": 0},
    {"product": "Кускус", "weight_g": 60, "calories": 215, "protein": 7, "fats": 1, "carbs": 45, "fiber": 1.3},
    {"product": "Кабачок", "weight_g": 100, "calories": 30, "protein": 1, "fats": 1, "carbs": 5, "fiber": 1},
]
TOTALS = {"calories": 495, "protein": 38, "fats": 14, "carbs": 55, "fiber": 2.3}


@pytest.mark.parametrize(
    "text,exclude",
    [
        ("без кускуса", ("кускуса",)),
        ("Без кускуса и соуса", ("кускуса", "соуса")),
        ("минус кускус", ("кускус",)),
        ("убери кабачок", ("кабачок",)),
    ],
)
def test_parse_exclusions(text, exclude):
    m = parse_modifiers(text)
    assert m.exclude == exclude and m.fraction is None and m.weight_g is None


@pytest.mark.parametrize(
    "text,fraction",
    [("половину", 0.5), ("съела половину", 0.5), ("треть", 1 / 3), ("четверть", 0.25)],
)
def test_parse_fraction(text, fraction):
    assert parse_modifiers(text).fraction == pytest.approx(fraction)


def test_parse_weight():
    m = parse_modifiers("это было 200 г")
    assert m.weight_g == 200 and not m.exclude


@pytest.mark.parametrize(
    "text",
    [
        "Завтрак: овсянка и кофе",
        "как мой вес?",
        "план: 2 яйца",
        "без сахара кола",
        "минус 2 яйца из плана на завтра",
    ],
)
def test_not_a_modifier(text):
    assert not parse_modifiers(text).is_modifier


def test_apply_exclusion_removes_item_and_recomputes():
    res = apply_modifiers(ITEMS, TOTALS, parse_modifiers("без кускуса"))
    assert [it["product"] for it in res.items] == ["Куриные стрипсы", "Кабачок"]
    assert res.totals["calories"] == pytest.approx(280) and res.removed[0]["product"] == "Кускус" and not res.unmatched


def test_apply_exclusion_declension_and_unmatched():
    res = apply_modifiers(ITEMS, TOTALS, parse_modifiers("без кабачков и соуса"))
    assert [it["product"] for it in res.items] == ["Куриные стрипсы", "Кускус"] and res.unmatched == ["соуса"]


def test_apply_fraction_scales_everything():
    res = apply_modifiers(ITEMS, TOTALS, parse_modifiers("половину"))
    assert res.items[1]["weight_g"] == 30 and res.items[1]["calories"] == pytest.approx(107.5)
    assert res.totals["calories"] == pytest.approx(247.5)


def test_apply_weight_only_for_single_item():
    single = [dict(ITEMS[0])]
    res = apply_modifiers(
        single,
        {"calories": 250, "protein": 30, "fats": 12, "carbs": 5, "fiber": 0},
        parse_modifiers("это было 200 г"),
    )
    assert res.items[0]["weight_g"] == 200 and res.items[0]["calories"] == pytest.approx(250 * 200 / 150)
    multi = apply_modifiers(ITEMS, TOTALS, parse_modifiers("200 г"))
    assert multi.items == ITEMS and multi.unmatched == ["200 г"]


def test_inputs_not_mutated():
    before = [dict(i) for i in ITEMS]
    apply_modifiers(ITEMS, TOTALS, parse_modifiers("без кускуса"))
    assert ITEMS == before


def test_describe():
    res = apply_modifiers(ITEMS, TOTALS, parse_modifiers("без кускуса и соуса"))
    s = describe_applied(res)
    assert "− Кускус ≈ 215 ккал" in s and "не нашёл в составе: соуса" in s


@pytest.mark.parametrize(
    "text", ["съела 300 г супа", "выпил 500 г воды", "200 г творога", "половину супа съела, остальное завтра"]
)
def test_food_sentences_with_numbers_are_not_modifiers(text):
    assert not parse_modifiers(text).is_modifier


@pytest.mark.parametrize(
    "text,w", [("это было 200 г", 200), ("200 г", 200), ("вес 150 гр", 150), ("примерно 180г", 180)]
)
def test_bare_weight_phrases_are_weight_modifiers(text, w):
    assert parse_modifiers(text).weight_g == w


def test_repeated_verb_and_punctuation_in_exclusion_list():
    assert parse_modifiers("без соли и без перца").exclude == ("соли", "перца")
    assert parse_modifiers("минус масло.").exclude == ("масло",)


def test_hyphenated_name_matches_product():
    """«без кус-куса» должно снимать item «Кускус» (прецедент 08.09.2026)."""
    res = apply_modifiers(ITEMS, TOTALS, parse_modifiers("Без кус-куса"))
    assert [it["product"] for it in res.items] == ["Куриные стрипсы", "Кабачок"]
    assert not res.unmatched
