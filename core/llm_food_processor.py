#!/usr/bin/env python3
"""
Обработка данных о еде от LLM Router.
Конвертирует ответ GPT в внутреннюю структуру meal_items/meal_totals.
"""

import re
import logging
from typing import Dict, List, Tuple

from .description_parser import (
    extract_products_from_description,
    normalize_product_name,
    get_default_unit_weight,
    is_zero_calorie_drink,
)
from .product_search import find_product
from .nutrition import calculate_nutrition, calculate_meal_totals

logger = logging.getLogger(__name__)


def process_llm_food_data(llm_data: Dict, description: str = None) -> Tuple[List[Dict], Dict[str, float]]:
    """
    Converts LLM Router 'food' data into internal meal structure.
    Calculates macros for items if LLM didn't provide them.
    
    Args:
        llm_data: Dict from llm_router.analyze_message (must be type='food')
        description: Original text description (optional, used for regex fallback)
        
    Returns:
        (meal_items, meal_totals)
    """
    if not llm_data or llm_data.get('type') != 'food':
        return [], {'calories': 0, 'protein': 0, 'fats': 0, 'carbs': 0}
        
    data = llm_data.get('data', {})
    items = data.get('items', [])
    meal_items = []
    
    # Pre-calculate regex items if description is available
    regex_items_map = {}
    if description:
        try:
            regex_products = extract_products_from_description(description)
            for p in regex_products:
                if p.get('weight'):
                    n_name = normalize_product_name(p['name'])
                    regex_items_map[n_name] = p['weight']
                    regex_items_map[p['name'].lower()] = p['weight']
        except Exception as e:
            print(f"Error in regex fallback: {e}")

    for item in items:
        logger.info(f"🔍 Processing LLM item: {item}")
        name = item.get('name', 'Unknown')
        weight = item.get('weight')
        
        # Приоритет: вес из описания (regex). Не перезаписывать явно указанный пользователем вес.
        regex_matched = False
        if description and regex_items_map:
            n_name = normalize_product_name(name)
            regex_weight = regex_items_map.get(n_name) or regex_items_map.get(name.lower())
            if regex_weight is None:
                name_tokens = set(name.lower().split())
                for r_name, r_weight in regex_items_map.items():
                    r_tokens = set(r_name.split())
                    if len(name_tokens & r_tokens) >= 1 and len(r_name) > 3 and len(name) > 3:
                        regex_weight = r_weight
                        break
            if regex_weight is not None:
                weight = regex_weight
                regex_matched = True
        
        # Только если пользователь НЕ указал вес — default для бутылок/порций
        if not regex_matched:
            default_weight = get_default_unit_weight(name)
            if default_weight > 0 and (not weight or weight < default_weight * 0.5):
                weight = default_weight
        
        # Fallback: regex (если не сработал выше)
        if (not weight or weight == 100) and description:
            weight = _try_regex_weight(name, weight, regex_items_map)
        
        # Пытаемся распарсить quantity если нет веса
        if (not weight or weight == 0) and item.get('quantity'):
            weight = _parse_quantity_weight(item.get('quantity'))
        
        # Приоритет: поиск в локальной БД
        norm_name = normalize_product_name(name)
        db_product = find_product(norm_name)
        if not db_product:
            db_product = find_product(name)
            
        if db_product:
            meal_item = _process_db_product(db_product, name, weight, item)
            meal_items.append(meal_item)
            continue
        
        # Если LLM дал макросы — используем их
        has_macros = item.get('calories') is not None and item.get('calories') > 0
        
        if has_macros:
            meal_item = _process_llm_macros(item, name, weight)
            meal_items.append(meal_item)
        elif weight and weight > 0:
            # Рассчитываем по локальной БД
            nutrition = calculate_nutrition(name, weight)
            cal, prot, fat, carb = nutrition['calories'], nutrition['protein'], nutrition['fats'], nutrition['carbs']
            if cal == 0 and not is_zero_calorie_drink(name):
                cal = round(weight * 0.12, 1)
                prot = round(weight * 0.03, 1)
                fat = round(weight * 0.06, 1)
                carb = round(weight * 0.12, 1)
            meal_items.append({
                'product': name,
                'weight_g': weight,
                'weight_source': 'llm',
                'calories': cal,
                'protein': prot,
                'fats': fat,
                'carbs': carb,
                'basis': nutrition.get('basis', 'raw'),
                'source': 'local_db'
            })
        else:
            # Нет веса, нет макросов — оцениваем
            meal_item = _estimate_unknown_product(item, name)
            meal_items.append(meal_item)
            
    # Check for explicit total_nutrition from LLM (Recipe Cards/Labels)
    total_nutrition = data.get('total_nutrition')
    computed_totals = calculate_meal_totals(meal_items)
    dish_name = data.get('dish_name', '')
    
    if total_nutrition and (total_nutrition.get('calories') or 0) > 0:
        if len(meal_items) == 1 and is_zero_calorie_drink(dish_name or (meal_items[0].get('product') if meal_items else '')):
            # LLM мог вернуть обычную колу — принудительно 0
            return meal_items, {'calories': 0.0, 'protein': 0.0, 'fats': 0.0, 'carbs': 0.0}
        if len(meal_items) == 1:
            logger.info(f"✅ Using explicit total nutrition from LLM (Recipe/Label): {total_nutrition}")
            return meal_items, {
                'calories': float(total_nutrition.get('calories', 0)),
                'protein': float(total_nutrition.get('protein', 0)),
                'fats': float(total_nutrition.get('fats', 0)),
                'carbs': float(total_nutrition.get('carbs', 0))
            }
        else:
            logger.info(f"⚠️  Ignoring total_nutrition for multi-item meal (len={len(meal_items)}), using computed totals: {computed_totals}")

    return meal_items, computed_totals


# --------------- Вспомогательные функции ---------------

def _try_regex_weight(name: str, current_weight, regex_items_map: dict):
    """Пробует найти вес продукта в regex-результатах."""
    n_name = normalize_product_name(name)
    
    regex_weight = regex_items_map.get(n_name) or regex_items_map.get(name.lower())
    
    # Fuzzy search
    if not regex_weight:
        name_tokens = set(name.lower().split())
        for r_name, r_weight in regex_items_map.items():
            r_tokens = set(r_name.split())
            if len(name_tokens & r_tokens) >= 1 and len(r_name) > 3 and len(name) > 3:
                regex_weight = r_weight
                break
    
    if regex_weight:
        if not current_weight:
            return regex_weight
        elif current_weight == 100 and regex_weight != 100:
            return regex_weight
    
    return current_weight


def _parse_quantity_weight(quantity) -> float:
    """Парсит вес из строки quantity (мл, л, г, кг)."""
    qty_str = str(quantity).lower().strip()
    
    patterns = [
        (r'(\d+(?:[.,]\d+)?)\s*(?:мл|ml|milliliter)', 1.0),
        (r'(\d+(?:[.,]\d+)?)\s*(?:л|l|liter)', 1000.0),
        (r'(\d+(?:[.,]\d+)?)\s*(?:г|g|gram)', 1.0),
        (r'(\d+(?:[.,]\d+)?)\s*(?:кг|kg|kilogram)', 1000.0),
    ]
    
    for pattern, multiplier in patterns:
        match = re.search(pattern, qty_str)
        if match:
            try:
                return float(match.group(1).replace(',', '.')) * multiplier
            except ValueError:
                pass
    return 0


def _process_db_product(db_product: Dict, name: str, weight, item: Dict) -> Dict:
    """Обрабатывает продукт, найденный в локальной БД."""
    logger.info(f"✅ Product found in DB (overriding LLM): {name}")
    
    final_weight = weight
    weight_src = 'llm'
    
    if not final_weight:
        final_weight = db_product.get('weight_g')
        if final_weight:
            weight_src = 'db_default'
        else:
            try:
                qty = float(item.get('quantity', 1))
            except (ValueError, TypeError):
                qty = 1.0
            if not qty or qty <= 0: qty = 1.0
            
            unit_weight = get_default_unit_weight(name)
            if unit_weight > 0:
                final_weight = unit_weight * qty
                weight_src = 'estimate'
    
    if not final_weight:
        logger.warning(f"Product {name} found in DB but no weight determined. Using 100g default.")
        final_weight = 100.0
        weight_src = 'default_100g'

    multiplier = final_weight / 100.0
    
    return {
        'product': db_product.get('name', name),
        'weight_g': final_weight,
        'weight_source': weight_src,
        'calories': round(db_product.get('calories_per_100g', 0) * multiplier, 1),
        'protein': round(db_product.get('protein_per_100g', 0) * multiplier, 1),
        'fats': round(db_product.get('fats_per_100g', 0) * multiplier, 1),
        'carbs': round(db_product.get('carbs_per_100g', 0) * multiplier, 1),
        'source': 'local_db_priority',
        'note': db_product.get('note')
    }


def _process_llm_macros(item: Dict, name: str, weight) -> Dict:
    """Обрабатывает продукт, для которого LLM дал макросы."""
    final_weight = weight
    weight_src = 'llm'
    
    if not final_weight:
        try:
            qty = float(item.get('quantity', 1))
        except (ValueError, TypeError):
            qty = 1.0
        if not qty or qty <= 0:
            qty = 1.0
            
        unit_weight = get_default_unit_weight(name)
        if unit_weight > 0:
            final_weight = unit_weight * qty
            weight_src = 'estimate'
    
    # Напитки без калорий: LLM часто путает с обычной колой — принудительно 0
    if is_zero_calorie_drink(name):
        return {
            'product': name,
            'weight_g': final_weight,
            'weight_source': weight_src,
            'calories': 0.0,
            'protein': 0.0,
            'fats': 0.0,
            'carbs': 0.0,
            'source': 'llm_router_zero_drink',
        }
            
    return {
        'product': name,
        'weight_g': final_weight,
        'weight_source': weight_src,
        'calories': float(item.get('calories') or 0),
        'protein': float(item.get('protein') or 0),
        'fats': float(item.get('fats') or 0),
        'carbs': float(item.get('carbs') or 0),
        'source': 'llm_router'
    }


def _estimate_unknown_product(item: Dict, name: str) -> Dict:
    """Оценивает продукт без веса и макросов."""
    try:
        qty = float(item.get('quantity', 1))
    except (ValueError, TypeError):
        qty = 1.0
    if not qty or qty <= 0: qty = 1.0
    
    unit_weight = get_default_unit_weight(name)
    
    if unit_weight > 0:
        estimated_weight = unit_weight * qty
    else:
        estimated_weight = 200.0  # Стандартная порция
    
    nutrition = calculate_nutrition(name, estimated_weight)
    cal = nutrition['calories']
    prot = nutrition['protein']
    fat = nutrition['fats']
    carb = nutrition['carbs']
    source = 'local_db_estimate'
    
    if cal == 0:
        # Грубая оценка (~150 ккал на 100г)
        cal = round(estimated_weight * 1.5, 1)
        prot = round(estimated_weight * 0.08, 1)
        fat = round(estimated_weight * 0.06, 1)
        carb = round(estimated_weight * 0.12, 1)
        source = 'rough_estimate'
        logger.info(f"⚠️ Rough estimate for '{name}' ({estimated_weight}g): {cal} kcal")
    
    return {
        'product': name,
        'weight_g': estimated_weight,
        'weight_source': 'estimate' if unit_weight > 0 else 'default_portion',
        'weight_estimated': True,
        'calories': cal,
        'protein': prot,
        'fats': fat,
        'carbs': carb,
        'source': source
    }
