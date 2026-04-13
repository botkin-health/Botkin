#!/usr/bin/env python3
"""
Обработка блюд с учётом данных меню (OCR из фото меню).
Пересчёт КБЖУ на основе указанного веса и данных из фото.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .description_parser import extract_products_from_description, apply_portion_multiplier, normalize_product_name
from .nutrition import calculate_nutrition, calculate_meal_totals

logger = logging.getLogger(__name__)


def process_meal_description_with_menu(
    description: str,
    menu_data: Dict,
    photo_paths: Optional[List[Path]] = None,
    portion_multiplier: float = 1.0,
    api_key: Optional[str] = None,
) -> Tuple[List[Dict], Dict[str, float]]:
    """
    Обрабатывает описание блюда с учетом данных меню.
    Если в описании указан вес для продукта из меню, пересчитывает КБЖУ на этот вес.
    Дополнительные продукты из описания добавляются к результату.

    Args:
        description: Описание блюда
        menu_data: Данные меню (dish_name, calories, protein, fats, carbs на 100г)
        photo_paths: Список путей к фото (опционально)
        portion_multiplier: Множитель порции
        api_key: API ключ Google Cloud Vision (опционально)

    Returns:
        Кортеж (meal_items, meal_totals):
        - meal_items: список продуктов с КБЖУ
        - meal_totals: общие КБЖУ
    """
    # Извлекаем продукты из компонентов меню или описания
    products = _extract_products(description, menu_data)

    # Применяем множитель порции ТОЛЬКО если продукты НЕ из menu_data
    products_from_menu = any(p.get("source") in ("menu_ocr", "menu_ocr_component") for p in products)
    if portion_multiplier != 1.0 and not products_from_menu:
        products = apply_portion_multiplier(products, portion_multiplier)

    # Дедупликация
    products = _deduplicate_products(products)

    # КБЖУ из меню
    menu_nutrition = _get_menu_nutrition_per_100g(menu_data)
    menu_dish_name = menu_data.get("dish_name", "").lower()
    menu_weight = menu_data.get("weight")

    logger.info(f"Обработка {len(products)} продуктов с учетом меню: {menu_dish_name}")
    logger.info(
        f"КБЖУ из меню (на 100г): {menu_nutrition['calories']} ккал, "
        f"Б: {menu_nutrition['protein']}г, Ж: {menu_nutrition['fats']}г, У: {menu_nutrition['carbs']}г"
    )

    meal_items = []
    for product in products:
        product_name = product.get("name", "").lower()
        product_weight = product.get("weight")

        is_menu_product = _is_menu_product(product, product_name, menu_dish_name, description)

        if is_menu_product:
            logger.info(f"  ✅ Продукт '{product_name}' соответствует меню")
            meal_item = _process_menu_product(product, product_weight, menu_data, menu_nutrition, menu_weight)
            meal_items.append(meal_item)
        else:
            logger.info(f"  ❌ Продукт '{product_name}' НЕ соответствует меню, обрабатываем как обычный продукт")
            meal_item = _process_regular_product(product, description)
            if meal_item:
                meal_items.append(meal_item)

    meal_totals = calculate_meal_totals(meal_items)
    return meal_items, meal_totals


# --------------- Вспомогательные функции ---------------


def _extract_products(description: str, menu_data: Dict) -> List[Dict]:
    """Извлекает продукты из компонентов меню или описания."""
    products = []

    if menu_data and menu_data.get("components"):
        logger.info(f"✅ Найдено {len(menu_data['components'])} компонентов от ИИ.")
        for comp in menu_data["components"]:
            products.append(
                {
                    "name": comp.get("name"),
                    "weight": comp.get("weight"),
                    "calories": comp.get("calories"),
                    "protein": comp.get("protein"),
                    "fats": comp.get("fats"),
                    "carbs": comp.get("carbs"),
                    "source": "menu_ocr_component",
                    "menu_data": menu_data,
                }
            )

    if not products:
        products = extract_products_from_description(description)

    if not products and menu_data:
        dish_name = menu_data.get("dish_name", "Блюдо из меню")
        logger.info(f"В описании не найдено продуктов, добавляем блюдо из меню: {dish_name}")
        products = [{"name": dish_name, "weight": None, "source": "menu_ocr"}]

    return products


def _deduplicate_products(products: List[Dict]) -> List[Dict]:
    """Убирает дубликаты продуктов по нормализованному названию и весу."""
    seen = set()
    unique = []

    for product in products:
        product_name = product.get("name", "").lower().strip()
        product_name_clean = re.sub(r"\s*(переку|перекус|обед|завтрак|ужин|бранч|полдник)\s*$", "", product_name)
        normalized_name = normalize_product_name(product_name_clean)
        product_weight = product.get("weight") or 0

        # Нормализация картошки
        if "картош" in normalized_name or "картофел" in normalized_name:
            if "варен" in normalized_name or "отварн" in normalized_name:
                normalized_name = "картофель отварной"
            elif "жарен" in normalized_name:
                normalized_name = "картофель жареный"
            elif "печен" in normalized_name or "запечен" in normalized_name:
                normalized_name = "картофель запечённый"
            else:
                normalized_name = "картофель"

        key = (normalized_name, round(product_weight, 1))
        if key not in seen:
            seen.add(key)
            product["name"] = normalized_name
            unique.append(product)
        else:
            logger.info(f"  ⚠️  Пропущен дубликат: '{product_name}' ({normalized_name}, {product_weight}г)")

    return unique


def _get_menu_nutrition_per_100g(menu_data: Dict) -> Dict[str, float]:
    """Извлекает КБЖУ на 100г из данных меню."""
    nutrition_per_100g = menu_data.get("nutrition_per_100g", {})

    if nutrition_per_100g:
        return {
            "calories": nutrition_per_100g.get("calories") or 0,
            "protein": nutrition_per_100g.get("protein") or 0,
            "fats": nutrition_per_100g.get("fats") or 0,
            "carbs": nutrition_per_100g.get("carbs") or 0,
        }

    menu_weight = menu_data.get("weight")
    if menu_weight and menu_weight > 0:
        m = 100.0 / menu_weight
        return {
            "calories": (menu_data.get("calories") or 0) * m,
            "protein": (menu_data.get("protein") or 0) * m,
            "fats": (menu_data.get("fats") or 0) * m,
            "carbs": (menu_data.get("carbs") or 0) * m,
        }

    return {
        "calories": menu_data.get("calories") or 0,
        "protein": menu_data.get("protein") or 0,
        "fats": menu_data.get("fats") or 0,
        "carbs": menu_data.get("carbs") or 0,
    }


def _is_menu_product(product: Dict, product_name: str, menu_dish_name: str, description: str) -> bool:
    """Проверяет, соответствует ли продукт блюду из меню."""
    if product.get("source") == "menu_ocr_component":
        return True

    stop_words = {
        "в",
        "на",
        "с",
        "из",
        "для",
        "и",
        "или",
        "как",
        "что",
        "это",
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "for",
        "with",
        "калининградский",
        "кусок",
        "соус",
        "унаги",
        "стерилизованные",
        "консервы",
    }
    menu_keywords = {w for w in re.findall(r"\b\w+\b", menu_dish_name) if len(w) > 2 and w not in stop_words}
    product_keywords = {w for w in re.findall(r"\b\w+\b", product_name) if len(w) > 2 and w not in stop_words}

    # Проверка рыбы
    is_fish = _check_fish_match(product_name, menu_dish_name, description)

    if (
        is_fish
        or len(menu_keywords & product_keywords) > 0
        or any(kw in product_name for kw in menu_keywords if len(kw) > 3)
        or any(kw in menu_dish_name for kw in product_keywords if len(kw) > 3)
    ):
        return True

    # Проверка по описанию
    description_lower = description.lower()
    for keyword in menu_keywords:
        if len(keyword) > 3:
            pattern = rf"\d+\s*(?:г|грамм|g)\s+.*?{re.escape(keyword)}|{re.escape(keyword)}.*?\d+\s*(?:г|грамм|g)"
            if re.search(pattern, description_lower) and keyword in product_name:
                return True

    return False


def _check_fish_match(product_name: str, menu_dish_name: str, description: str) -> bool:
    """Проверяет совпадение рыбы между продуктом и меню."""
    fish_variants = {
        "угорь": ["угря", "угрем", "угре"],
        "лосось": ["лосося", "лососем", "лососе"],
        "тунец": ["тунца", "тунцом", "тунце"],
        "сельдь": ["сельди", "сельдью"],
        "скумбрия": ["скумбрии", "скумбрией"],
        "сардина": ["сардины", "сардиной", "сардине"],
    }

    fish_in_menu = None
    fish_in_product = None

    for base, forms in fish_variants.items():
        if base in menu_dish_name or any(f in menu_dish_name for f in forms):
            fish_in_menu = base
        if base in product_name or any(f in product_name for f in forms):
            fish_in_product = base

    if fish_in_menu and fish_in_product and fish_in_menu == fish_in_product:
        return True

    # Рыбные консервы
    if not fish_in_menu and ("рыбные" in menu_dish_name or "консервы" in menu_dish_name) and fish_in_product:
        desc_lower = description.lower()
        for base, forms in fish_variants.items():
            if base == fish_in_product:
                pattern = rf"\d+\s*(?:г|грамм|g)\s+.*?(?:{base}|{'|'.join(forms)})|(?:{base}|{'|'.join(forms)}).*?\d+\s*(?:г|грамм|g)"
                if re.search(pattern, desc_lower):
                    return True

    return False


def _process_menu_product(product: Dict, product_weight, menu_data: Dict, menu_nutrition: Dict, menu_weight) -> Dict:
    """Обрабатывает продукт из меню."""
    # Компоненты с собственными КБЖУ
    if product.get("source") == "menu_ocr_component" and product.get("calories") is not None:
        return {
            "product": product.get("name", menu_data.get("dish_name", "Продукт из меню")),
            "weight_g": round(product_weight, 2) if product_weight else None,
            "weight_source": "description",
            "weight_estimated": False,
            "calories": round(product.get("calories", 0), 1),
            "protein": round(product.get("protein", 0), 1),
            "fats": round(product.get("fats", 0), 1),
            "carbs": round(product.get("carbs", 0), 1),
            "source": "menu_ocr_component",
        }

    if product_weight and product_weight > 0:
        m = product_weight / 100.0
        return {
            "product": product.get("name", menu_data.get("dish_name", "Продукт из меню")),
            "weight_g": round(product_weight, 2),
            "weight_source": "description",
            "weight_estimated": False,
            "calories": round(menu_nutrition["calories"] * m, 1),
            "protein": round(menu_nutrition["protein"] * m, 1),
            "fats": round(menu_nutrition["fats"] * m, 1),
            "carbs": round(menu_nutrition["carbs"] * m, 1),
            "source": "menu_ocr",
        }

    # Вес не указан
    weight_to_use = menu_weight if menu_weight else 100.0
    m = weight_to_use / 100.0
    return {
        "product": product.get("name", menu_data.get("dish_name", "Продукт из меню")),
        "weight_g": weight_to_use,
        "weight_source": "menu",
        "weight_estimated": False,
        "calories": menu_nutrition["calories"] * m,
        "protein": menu_nutrition["protein"] * m,
        "fats": menu_nutrition["fats"] * m,
        "carbs": menu_nutrition["carbs"] * m,
        "source": "menu_ocr",
    }


def _process_regular_product(product: Dict, description: str) -> Optional[Dict]:
    """Обрабатывает обычный продукт (не из меню)."""
    if product.get("weight") and product["weight"] > 0:
        nutrition = calculate_nutrition(
            product["name"], product["weight"], description=description, basis=product.get("basis")
        )
        return {
            "product": product["name"],
            "weight_g": round(product["weight"], 2),
            "weight_source": product.get("source", "unknown"),
            "weight_estimated": product.get("source") in ["portion_estimate", "default_portion"],
            "calories": nutrition["calories"],
            "protein": nutrition["protein"],
            "fats": nutrition["fats"],
            "carbs": nutrition["carbs"],
            "basis": nutrition.get("basis", "raw"),
            "source": "local_db",
        }

    if product.get("source") == "description_simple":
        default_weights = {
            "кофе": 250,
            "чай": 250,
            "сок": 200,
            "вода": 250,
            "молоко": 250,
        }
        default_weight = default_weights.get(product["name"].lower(), 100)
        nutrition = calculate_nutrition(product["name"], default_weight)
        return {
            "product": product["name"],
            "weight_g": default_weight,
            "weight_source": "default_portion",
            "weight_estimated": True,
            "calories": nutrition["calories"],
            "protein": nutrition["protein"],
            "fats": nutrition["fats"],
            "carbs": nutrition["carbs"],
            "source": "local_db",
        }

    return None
