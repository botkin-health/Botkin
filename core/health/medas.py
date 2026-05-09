"""
MEDAS — Mediterranean Diet Adherence Screener (PREDIMED 2011, Schröder et al.).

Считает приверженность средиземноморской диете по реальным данным
nutrition_log из NutriLogBot. 14 правил, каждое 0/1, итог 0–14 →
конвертируется в 0–100 для AHA Life's Essential 8.

Используется в:
  - telegram-bot/dashboard_generator.py — LE8 panel "Диета"
  - scripts/analysis/medas_score.py — standalone CLI для анализа

Источник методики:
  Schröder H. et al. A Short Screener Is Valid for Assessing Mediterranean
  Diet Adherence among Older Spanish Men and Women.
  J. Nutr. 2011;141(6):1140-1145.
  https://pubmed.ncbi.nlm.nih.gov/21508208/

Архитектура:
  classify_food(name) → list[str]  — теги категорий продукта
  to_portions(grams, tag) → float  — конвертация граммы→порции для MEDAS
  compute_medas(items, days) → dict — основной расчёт
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

# ── Классификатор продуктов (regex → теги) ──────────────────────────────────
# Один продукт может иметь несколько тегов (томатный соус → vegetable + tomato).
# Порядок ВАЖЕН: первое совпадение выигрывает.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    # ── жиры ──────────────────────────────────────────────────────────────
    (r"оливков\w*\s+масл|olive\s*oil|extra\s*virgin", ["olive_oil"]),
    (r"подсолн\w*\s+масл|кукуруз\w*\s+масл|раст\w*\s+масл", ["vegetable_oil"]),
    (r"слив\w*\s+масл|маргарин|гхи|ghee|топл\w*\s+масл", ["butter_margarine"]),
    # ── рыба и морепродукты ───────────────────────────────────────────────
    (r"лосос|сёмг|форель|скумбри|сардин|селёд|сельд|тунец|тунца|анчоус|икра|сайр|палтус|сом\b", ["fish", "fatty_fish"]),
    (r"рыб|уха\b|треск|минта|пикш|судак|щук|карп|хек|окун|пангасиус|тилапи|дорад|сибас|кефал|линь|плотв", ["fish"]),
    (r"мидии|кальмар|креветк|осьминог|устриц|морепрод|краб(?!ов\w*\s+пал)|омар|лангуст", ["seafood"]),
    # ── мясо ──────────────────────────────────────────────────────────────
    (r"бекон|сосиск|сардель|колбас|ветчин|пастрам|салями|шинк|карбонат", ["red_meat", "processed_meat"]),
    (r"говяди?н|телятин|свинин|баран|кроли?к|оленин|конин|стейк|тушёнк|тушенк|холодец|холодц", ["red_meat"]),
    (r"кур\w*\s|курин|куриц|курица|индейк|индюш|утка|утиная|утин\w+\s+филе|перепел|chicken|turkey", ["poultry"]),
    (r"гуляш|плов\b|рагу|жаркое|шаурм|бургер|котлет|тефтел|шашлык|пельмен|манты|хинкали|чахохб", ["mixed_meat"]),
    (r"сэндвич|бутерброд|сандвич|сосис.*тест|тост.*ветчин|гриль.?чиз", ["mixed_meat"]),
    (r"бульон\s+говяж|говяж\w*\s+бульон", ["red_meat"]),
    (r"бульон\s+кур|кур\w*\s+бульон", ["poultry"]),
    # ── молочка ───────────────────────────────────────────────────────────
    (r"творог|cottage", ["dairy"]),
    (r"йогурт|кефир|ряженк|тан|айран|катык|простокваш|варенец", ["dairy", "fermented"]),
    (r"квашен|кимчи|sauerkraut|natto|kombucha|комбуч|чайн\w*\s+гриб", ["fermented"]),
    (r"сметан", ["dairy_full_fat"]),
    (r"молоко|молочн\w*\s+продукт", ["dairy"]),
    (r"сыр\b|cheese|пармезан|моцарелл|чеддер|фета|бри|камамбер|адыгейск|сулугун|маскарпоне|рикотт", ["cheese"]),
    (r"мороженое|мороженого|пломбир", ["sweets"]),
    # ── фрукты ────────────────────────────────────────────────────────────
    (r"яблок|груш|банан|апельсин|мандарин|лимон|грейпфрут|киви|ананас|манго|папайя|хурм|айв|инжир", ["fruit"]),
    (r"клубник|малин|черник|голубик|ежевик|смородин|вишн|черешн|клюкв|брусник|облепих", ["fruit", "berry"]),
    (r"виноград|слив\b|абрикос|персик|нектарин|алыч|финик|изюм|чернослив|курага|сухофрукт", ["fruit"]),
    (r"арбуз|дыня|авокадо|памело|помело|pomelo|гранат|pomegran", ["fruit"]),
    # ── овощи ─────────────────────────────────────────────────────────────
    (r"помидор|томат|tomate", ["vegetable", "tomato"]),
    (r"огур[еч]|cucumb", ["vegetable"]),
    (r"перец|болгарск|paprika", ["vegetable"]),
    (r"капуст|брокколи|цветная|кольраби|брюссель|пекинск", ["vegetable", "cruciferous"]),
    (r"морков|свёкл|свекл|редис|редьк|репа|пастернак|турнепс", ["vegetable"]),
    (r"лук\b|чеснок|порей|шалот|зелёный\s+лук|зелен\w*\s+лук", ["vegetable"]),
    (
        r"шпинат|салат\s+(?:листо|айсбер|ромэн|романо)|руккол|латук|кейл|мангольд|зелён\w*\s+салат|зелен\w*\s+салат",
        ["vegetable", "leafy_greens"],
    ),
    (r"кабач|цуккин|баклажан|тыкв", ["vegetable"]),
    (r"спарж|сельдер|укроп|петрушк|базилик|кинз|мят|зелень|зелён\w*\s+трав", ["vegetable", "herbs"]),
    (r"гриб|шампиньон|вёшенк|шиитаке|боров|подосинов|опят|лисичк|трюф", ["vegetable"]),
    (r"оливк\b|маслин", ["vegetable", "olive"]),
    (r"^лечо$|рататуй|каперонат|пиперад|овощн\w*\s+рагу|овощн\w*\s+ассорти|сот\w+\s+овощ", ["vegetable", "tomato"]),
    (r"^овощ|овощи\s+(?:на\s+пару|свеж|микс|с\s+|на\s+гриле|запечён|тушён)", ["vegetable"]),
    (r"^салат\s|^салат$|овощн\w*\s+салат|винегрет", ["vegetable"]),
    (r"батат|sweet\s*potato", ["vegetable"]),
    # ── бобовые ──────────────────────────────────────────────────────────
    (r"фасол|чечевиц|нут\b|горох|боб\w*\s+зелён|зелён\w*\s+боб|маш\b|соя|тофу|темпе|эдамаме|hummus|хумус", ["legume"]),
    # ── орехи и семена ────────────────────────────────────────────────────
    (r"миндал|фундук|кешью|пекан|грецк\w*\s+орех|кедров|фисташ|бразильск\w*\s+орех|макадам|каштан", ["nuts"]),
    (r"\bорех\w*\b|арахис|peanut|nut\b", ["nuts"]),
    (
        r"кунжут|подсолн\w*\s+семеч|подсолн\w*\s+семя|чиа|лён|льна|льнян\w*\s+семя|тыквенн\w*\s+семя|смесь\s+семян",
        ["nuts", "seeds"],
    ),
    # ── злаки ────────────────────────────────────────────────────────────
    (r"гречк|гречн|перлов|пшен[ао]|булгур|кускус|киноа|амарант|полб|спельт|рожь|ячмен", ["whole_grain"]),
    (r"овсян|овсяная|овсяных|мюсл|granola", ["whole_grain"]),
    (
        r"бородинск|цельнозернов|whole.*grain|whole.*wheat|ржан\w*\s+хлеб|хлеб\s+зернов|хлебц|зернов\w*\s+хлеб|ячнев",
        ["whole_grain"],
    ),
    (
        r"белый\s+хлеб|серый\s+хлеб|батон|булк|лаваш(?!\s+армянск)|тост\b|пита|сухар|крендел|калач|бубл",
        ["refined_grain"],
    ),
    (r"макарон|паст[аы]\b|спагетти|равиол|лазань|тортеллини|вермишель|лапш", ["refined_grain"]),
    (r"рис\b|плов(?!\s+грибной)", ["refined_grain"]),
    (r"картоф|картошк|пюре\s+карто|чипс\b|фри\b|french\s+fries", ["potato"]),
    # ── яйца ─────────────────────────────────────────────────────────────
    (r"\bяйц|\bяиц|омлет|глазун|болтун|пашот|scrambled|frittata", ["egg"]),
    # ── сладкое ──────────────────────────────────────────────────────────
    (r"шоколад|конфет|chocolate|кэроб|нутелл|nutella|сникерс|марс\b|трюфел", ["sweets"]),
    (
        r"торт|пирож|кекс|маффин|капкейк|пончик|круассан|штрудел|эклер|тирамису|чизкейк|брауни|печень|сочник|плюшк|ватрушк|рулетик",
        ["sweets", "pastry"],
    ),
    (r"варен|джем|мармелад|повидл|желе\b|зефир|пастил|халв|щербет|нуга|карамел|ирис\b", ["sweets"]),
    (r"мёд\b|мед\b|honey", ["honey"]),
    (r"сахар(?!оз)|сахарн\w*\s+пес|саха́рн", ["added_sugar"]),
    (r"батончик|protein.*бар|bombbar", ["protein_bar"]),
    # ── напитки ──────────────────────────────────────────────────────────
    (r"вода\b|минералк|минер\w*\s+вод|сельтер|боржом|нарзан", ["water"]),
    (r"сок\s+(?:апельс|яблочн|виноград|томатн|мультифрукт)|свежевыжат\w*\s+сок", ["juice"]),
    (r"кокосов\w*\s+вода|coconut.*water", ["water"]),
    (r"кола\b|coca|пепси|спрайт|sprite|fanta|тархун|байкал|дюшес|лимонад", ["sugary_drink"]),
    (r"квас\b|морс\b|компот", ["sugary_drink"]),
    (r"чай\b|tea\b|латте\b|капучин|cappucci|mocha|мокк\b|раф\b|тоник|травян\w*\s+чай", ["coffee_tea"]),
    (
        r"кофе|coffee|эспрессо|американ|espresso|americano|filter\s+coffee|фильтр.?кофе|флет\s*вайт|flat\s*white",
        ["coffee_tea"],
    ),
    (
        r"вино\b|white.*wine|red.*wine|rosé|prosecc|шампанск|champagne|cava|шерри|sherry|порто\b|вермут",
        ["alcohol", "wine"],
    ),
    (r"пиво|beer|lager|эль\b|stout|porter|ale", ["alcohol", "beer"]),
    (
        r"водк|виски|whisky|whiskey|коньяк|cognac|джин|gin\b|ром\b|текил|tequil|самбука|ликёр|liqueur|sake",
        ["alcohol", "spirits"],
    ),
    # ── бад/добавки — игнорируются для MEDAS ─────────────────────────────
    (r"бад|whey|протеин|psyllium|псиллиум|омега|витамин|магний|зма\b|аминокислот", ["supplement"]),
]


# ── Стандартные размеры порций (граммы) ─────────────────────────────────────
PORTION_SIZES: dict[str, float] = {
    "olive_oil": 14,
    "vegetable_oil": 14,
    "butter_margarine": 14,
    "vegetable": 100,
    "fruit": 100,
    "berry": 100,
    "olive": 30,
    "nuts": 30,
    "seeds": 15,
    "fish": 125,
    "fatty_fish": 125,
    "seafood": 125,
    "red_meat": 100,
    "processed_meat": 50,
    "poultry": 100,
    "mixed_meat": 100,
    "egg": 60,
    "dairy": 200,
    "dairy_full_fat": 100,
    "fermented": 100,
    "cheese": 30,
    "legume": 150,
    "whole_grain": 80,
    "refined_grain": 80,
    "potato": 150,
    "sweets": 30,
    "pastry": 50,
    "protein_bar": 60,
    "honey": 15,
    "added_sugar": 5,
    "water": 250,
    "juice": 200,
    "sugary_drink": 250,
    "coffee_tea": 200,
    "alcohol": 150,
    "wine": 150,
}


def classify_food(food: str) -> list[str]:
    """Возвращает список тегов категорий для названия продукта.
    Пустой список = неклассифицирован.
    """
    fl = (food or "").lower().strip()
    if not fl:
        return []
    for pat, tags in CATEGORY_RULES:
        if re.search(pat, fl, re.IGNORECASE):
            return tags
    return []


def to_portions(grams: float, tag: str) -> float:
    """Конвертирует граммы → MEDAS-порции для конкретной категории."""
    size = PORTION_SIZES.get(tag, 100)
    return grams / size if size else 0


def compute_medas(
    nutrition_items: Iterable[dict],
    n_days: int,
    *,
    skip_wine_rule: bool = True,
) -> dict:
    """Расчёт MEDAS по списку «items» из nutrition_log.

    Args:
        nutrition_items: список dict с полями {date, food, amount}
                        (или {date, name, weight} — поддержка legacy формата).
        n_days: сколько дней включает выборка (для нормализации к "в среднем за день").
        skip_wine_rule: если True — пункт #8 (вино ≥7/нед) исключается из 14
                       (max становится 13/13 → 100). Современная медицина (UK Biobank
                       2018) показала что любой алкоголь повышает смертность,
                       AHA-LE8 не одобряет рекомендацию пить вино. Default=True.

    Returns:
        {
            "points": int (0..14),
            "max_points": int (13 or 14),
            "score_100": int (0..100),
            "verdict": "low" | "medium" | "high",
            "items": [(label, ok, detail), ...],
            "raw_metrics": {...},
            "unknown_count": int — сколько продуктов не удалось классифицировать,
        }
    """
    if n_days <= 0:
        return {
            "points": 0,
            "max_points": 14,
            "score_100": 0,
            "verdict": "low",
            "items": [],
            "raw_metrics": {},
            "unknown_count": 0,
        }

    daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    unknown_count = 0

    for item in nutrition_items:
        if not isinstance(item, dict):
            continue
        d_raw = item.get("date") or item.get("day")
        if isinstance(d_raw, (date, datetime)):
            d_str = d_raw.isoformat()[:10]
        elif isinstance(d_raw, str):
            d_str = d_raw[:10]
        else:
            continue
        food = (item.get("food") or item.get("name") or "").strip()
        grams = float(item.get("amount") or item.get("weight") or 0)
        if not food or grams <= 0:
            continue
        tags = classify_food(food)
        if not tags:
            unknown_count += 1
            continue
        for tag in tags:
            if tag == "supplement":
                continue
            daily[d_str][tag] += to_portions(grams, tag)

    # Усреднение по фактическому n_days (а не по len(daily) — там могут быть пропуски)
    def avg_per_day(tag: str) -> float:
        return sum(d.get(tag, 0) for d in daily.values()) / n_days

    def per_week(tag: str) -> float:
        return avg_per_day(tag) * 7

    olive_d = avg_per_day("olive_oil")
    sun_d = avg_per_day("vegetable_oil")
    butter_d = avg_per_day("butter_margarine")
    veg_d = avg_per_day("vegetable")
    fruit_d = avg_per_day("fruit") + avg_per_day("berry")
    red_meat_d = avg_per_day("red_meat") + avg_per_day("mixed_meat") + avg_per_day("processed_meat")
    sugary_d = avg_per_day("sugary_drink")
    legume_w = per_week("legume")
    fish_w = per_week("fish") + per_week("fatty_fish") + per_week("seafood")
    sweets_w = per_week("sweets") + per_week("pastry") + per_week("honey") * 0.3
    nuts_w = per_week("nuts") + per_week("seeds") * 0.5
    poultry_w = per_week("poultry")
    red_meat_w = per_week("red_meat") + per_week("mixed_meat")
    tomato_w = per_week("tomato")
    alcohol_w = per_week("alcohol")

    items = [
        (
            "Оливковое масло — основной жир",
            olive_d > sun_d and olive_d > butter_d and olive_d > 0.1,
            f"olive {olive_d:.2f} vs sunflower {sun_d:.2f}, butter {butter_d:.2f} порц/д",
        ),
        ("≥4 ст.л. оливкового масла в день", olive_d >= 4, f"{olive_d:.2f} ст.л./д"),
        ("≥2 порции овощей в день", veg_d >= 2, f"{veg_d:.2f} порц/д (порция = 100г)"),
        ("≥3 порции фруктов в день", fruit_d >= 3, f"{fruit_d:.2f} порц/д"),
        ("<1 порции красного/обработанного мяса в день", red_meat_d < 1, f"{red_meat_d:.2f} порц/д"),
        ("<1 сливочного масла/маргарина в день", butter_d < 1, f"{butter_d:.2f} порц/д"),
        ("<1 сладкого газированного напитка в день", sugary_d < 1, f"{sugary_d:.2f} порц/д"),
        (
            "≥7 бокалов вина в неделю (PREDIMED-MEDAS, спорное правило)",
            alcohol_w >= 7,
            f"{alcohol_w:.1f} порц/нед — AHA не одобряет alkohol",
        ),
        ("≥3 порции бобовых в неделю", legume_w >= 3, f"{legume_w:.1f} порц/нед"),
        ("≥3 порции рыбы в неделю", fish_w >= 3, f"{fish_w:.1f} порц/нед"),
        ("<2 раз/нед сладкое/выпечка", sweets_w < 2, f"{sweets_w:.1f} порц/нед"),
        ("≥3 порции орехов в неделю", nuts_w >= 3, f"{nuts_w:.1f} порц/нед"),
        (
            "Птица чаще красного мяса",
            poultry_w > red_meat_w and poultry_w >= 1,
            f"poultry {poultry_w:.1f} vs red {red_meat_w:.1f} порц/нед",
        ),
        ("≥2/нед блюда с томатной/овощной основой", tomato_w >= 2, f"{tomato_w:.1f} порц/нед"),
    ]

    # Если skip_wine_rule — исключаем пункт #8 (alcohol) из подсчёта
    if skip_wine_rule:
        # удаляем правило о вине (индекс 7 в нумерации — 8-й пункт MEDAS)
        items_for_score = [it for i, it in enumerate(items) if i != 7]
    else:
        items_for_score = items

    points = sum(1 for _, ok, _ in items_for_score if ok)
    max_points = len(items_for_score)

    # Конвертация в 0-100. Калибрована под 13-балльную шкалу (без вина):
    #   ≤4 → 0-30 (низкая), 5-8 → 30-70 (средняя), 9-13 → 70-100 (высокая)
    if max_points == 13:
        if points <= 4:
            score = round(points / 4 * 30)
        elif points <= 8:
            score = round(30 + (points - 4) / 4 * 40)
        else:
            score = round(70 + (points - 8) / 5 * 30)
    else:  # 14-балльная
        if points <= 5:
            score = round(points / 5 * 30)
        elif points <= 9:
            score = round(30 + (points - 5) / 4 * 40)
        else:
            score = round(70 + (points - 9) / 5 * 30)
    score = max(0, min(100, score))

    if score < 40:
        verdict = "low"
    elif score < 70:
        verdict = "medium"
    else:
        verdict = "high"

    return {
        "points": points,
        "max_points": max_points,
        "score_100": score,
        "verdict": verdict,
        "items": items,  # все 14 для отображения
        "items_for_score": items_for_score,
        "raw_metrics": {
            "olive_oil_d": round(olive_d, 2),
            "veg_d": round(veg_d, 2),
            "fruit_d": round(fruit_d, 2),
            "red_meat_d": round(red_meat_d, 2),
            "fish_w": round(fish_w, 1),
            "legume_w": round(legume_w, 1),
            "nuts_w": round(nuts_w, 1),
            "sweets_w": round(sweets_w, 1),
            "alcohol_w": round(alcohol_w, 1),
            "tomato_w": round(tomato_w, 1),
        },
        "unknown_count": unknown_count,
    }
