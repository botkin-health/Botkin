"""Fallback fiber content (g per 100 g) for common foods.

Used when the LLM doesn't return fiber for an item. Keys are substrings matched
against a normalized (lowercase) product name — first match wins, so order
more specific keys before generic ones.

Sources: USDA FoodData Central, Roskomstat food tables (typical values).
"""

from typing import Optional

# Ordered: more specific names first.
_FIBER_PER_100G = [
    # Legumes / beans
    ("чечевиц", 7.9),
    ("нут", 7.6),
    ("фасол", 6.4),
    ("горох", 5.5),
    ("соя", 9.3),
    # Whole grains / cereals
    ("овсян", 10.0),  # oatmeal dry; cooked ~1.7 — accept as overestimate for dry-logged cases
    ("греч", 2.7),
    ("бурый рис", 1.8),
    ("коричневый рис", 1.8),
    ("дикий рис", 1.8),
    ("рис отварн", 0.4),
    ("рис варён", 0.4),
    ("белый рис", 0.4),
    ("рис", 0.4),
    ("пшён", 1.3),
    ("пшен", 1.3),
    ("перловк", 2.1),
    ("булгур", 4.5),
    ("кускус", 2.2),
    ("киноа", 2.8),
    ("киноа варён", 2.8),
    ("хлебц", 7.0),
    ("хлеб цельнозерн", 7.0),
    ("хлеб ржаной", 5.8),
    ("хлеб бородинск", 7.0),
    ("хлеб отрубной", 8.0),
    ("хлеб", 2.4),
    # Fruits
    ("авокадо", 6.7),
    ("малин", 6.5),
    ("ежевик", 5.3),
    ("груш", 3.1),
    ("яблок", 2.4),
    ("чернослив", 7.1),
    ("курага", 7.3),
    ("финик", 7.0),
    ("изюм", 3.7),
    ("апельсин", 2.4),
    ("мандарин", 1.8),
    ("лимон", 2.8),
    ("грейпфрут", 1.6),
    ("киви", 3.0),
    ("банан", 2.6),
    ("персик", 1.5),
    ("абрикос", 2.0),
    ("слив", 1.4),
    ("виноград", 0.9),
    ("черешн", 2.1),
    ("вишн", 2.1),
    ("клубник", 2.0),
    ("земляник", 2.0),
    ("черник", 2.4),
    ("голубик", 2.4),
    ("арбуз", 0.4),
    ("дын", 0.9),
    ("ананас", 1.4),
    ("манго", 1.6),
    ("хурм", 3.6),
    ("гранат", 4.0),
    # Vegetables
    ("артишок", 5.4),
    ("брокколи", 2.6),
    ("цветн капуст", 2.0),
    ("брюссельск", 3.8),
    ("кольрабы", 3.6),
    ("кольраби", 3.6),
    ("квашен капуст", 4.1),
    ("квашенн капуст", 4.1),
    ("капуст белокочанн", 2.5),
    ("капуст краснокочанн", 2.5),
    ("капуст пекинск", 1.2),
    ("капуст", 2.5),
    ("морковь", 2.8),
    ("свекл", 2.8),
    ("тыкв", 2.1),
    ("кабачок", 1.0),
    ("кабачк", 1.0),
    ("цукини", 1.0),
    ("баклажан", 3.0),
    ("перец сладк", 2.1),
    ("перец болгарск", 2.1),
    ("перец", 2.1),
    ("огурец", 0.5),
    ("огурц", 0.5),
    ("помидор", 1.2),
    ("томат", 1.2),
    ("редис", 1.6),
    ("редьк", 1.6),
    ("репа", 1.8),
    ("лук репчат", 1.7),
    ("лук зелён", 1.8),
    ("лук-порей", 1.8),
    ("чеснок", 2.1),
    ("шпинат", 2.2),
    ("салат", 1.3),
    ("рукол", 1.6),
    ("сельдерей", 1.6),
    ("спарж", 2.1),
    ("фенхел", 3.1),
    ("картофель", 1.8),
    ("картошк", 1.8),
    ("батат", 3.0),
    ("укроп", 2.1),
    ("петрушк", 3.3),
    ("кинза", 2.8),
    ("базилик", 1.6),
    # Nuts / seeds
    ("миндал", 12.5),
    ("фундук", 9.7),
    ("грецк орех", 6.7),
    ("кешью", 3.3),
    ("фисташк", 10.3),
    ("арахис", 8.5),
    ("орех", 7.0),
    ("семен подсолнечн", 8.6),
    ("семечк подсолнеч", 8.6),
    ("тыквенн семен", 6.0),
    ("льнян семен", 27.3),
    ("семена чиа", 34.4),
    ("чиа", 34.4),
    ("кунжут", 11.8),
    # Mushrooms
    ("гриб", 2.3),
    ("шампиньон", 2.3),
    ("вешенк", 2.3),
    ("лисичк", 3.8),
    # Berries / dried
    ("клюкв", 4.6),
    ("смородин", 4.3),
    ("крыжовник", 3.4),
    # Non-fiber explicit (meat/fish/dairy/fats): leave out → falls to 0 default
    # Confectionery / grains misc
    ("гречнев хлебц", 7.0),
    ("отруб", 24.0),
    ("мюсли", 7.0),
    ("гранол", 6.0),
]


def fiber_per_100g(name: str) -> Optional[float]:
    """Returns fiber g per 100g for a food name, or None if no match."""
    if not name:
        return None
    n = name.lower()
    for key, val in _FIBER_PER_100G:
        if key in n:
            return val
    return None


def estimate_fiber(name: str, weight_g: Optional[float]) -> float:
    """Estimate fiber grams for a given food item. Returns 0.0 if no match or no weight."""
    if not weight_g or weight_g <= 0:
        return 0.0
    per100 = fiber_per_100g(name)
    if per100 is None:
        return 0.0
    return round(per100 * weight_g / 100.0, 1)


def _item_name(it: dict) -> str:
    """Extract display name from an item dict, handling all three schemas
    (product / name / food) used across the codebase."""
    return str(it.get("product") or it.get("name") or it.get("food") or "")


def _item_weight(it: dict) -> float:
    """Extract weight in grams, handling weight_g / amount / weight field names."""
    w = it.get("weight_g")
    if w is None:
        w = it.get("amount")
    if w is None:
        w = it.get("weight")
    try:
        return float(w) if w is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def enrich_items_with_fiber(items: list) -> list:
    """Fill the `fiber` field on items that lack it, using estimate_fiber.

    Idempotent — items with existing fiber > 0 are never overwritten.
    Items with fiber = 0, None, or missing are re-estimated from name + weight.
    Mutates items in place (safe since they are fresh copies from SQLAlchemy JSONB).

    Handles all three item schemas in the codebase:
      - DB LLM/vision items: {"food": ..., "amount": ...}
      - internal meal_items: {"product": ..., "weight_g": ...}
      - supplements items:   {"name": ..., "weight_g": ..., "fiber": ...}

    Returns the same list for convenience.
    """
    for it in items:
        existing = it.get("fiber")
        if existing is not None:
            try:
                if float(existing) > 0:
                    continue
            except (TypeError, ValueError):
                pass
        estimated = estimate_fiber(_item_name(it), _item_weight(it))
        if estimated > 0:
            it["fiber"] = estimated
    return items


def sum_fiber(items: list) -> float:
    """Sum fiber across items (assumes items already enriched). Rounded to 1 decimal."""
    total = 0.0
    for it in items:
        v = it.get("fiber")
        try:
            total += float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            pass
    return round(total, 1)
