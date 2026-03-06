#!/usr/bin/env python3
"""
Сервис для расчёта КБЖУ с интеграцией новых модулей извлечения весов
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import time

try:
    import requests
except ImportError:
    requests = None

# Пытаемся импортировать утилиту для ключа
try:
    from .chatgpt_vision import get_openai_api_key
except ImportError:
    # Фолбек
    def get_openai_api_key():
        return os.getenv('OPENAI_API_KEY')

# Импортируем новые модули
from .description_parser import (
    parse_meal_description as parse_meal_description_new,
    apply_portion_multiplier,
    normalize_product_name,
    is_zero_calorie_drink,
)
from .weight_extraction import extract_weight_from_photo

# Импортируем поиск продуктов
try:
    from .product_search import find_product, search_product_online, load_products_db
except ImportError:
    # Если модуль не найден, создаем заглушки
    def find_product(name: str) -> Optional[Dict]:
        return None
    
    def search_product_online(name: str) -> Optional[Dict]:
        return None
    
    def load_products_db() -> Dict:
        return {}

logger = logging.getLogger(__name__)

# Загружаем базу продуктов
PRODUCTS_DB = load_products_db()


def parse_meal_description(
    description: str,
    photo_paths: Optional[List[Path]] = None,
    api_key: Optional[str] = None,
    portion_multiplier: float = 1.0
) -> List[Dict]:
    """
    Парсит описание блюда и извлекает информацию о продуктах.
    Использует новый улучшенный парсер с поддержкой нескольких фото.
    
    Args:
        description: Описание блюда
        photo_paths: Список путей к фото (опционально)
        api_key: API ключ Google Cloud Vision (опционально)
        portion_multiplier: Множитель порции (например, 0.5 для половины)
        
    Returns:
        Список продуктов с весами и информацией:
        [{'name': 'куриное филе', 'weight': 192.8, 'source': 'photo'}, ...]
    """
    # Получаем API ключ используя единую функцию
    if not api_key:
        try:
            from .api_key_loader import get_google_vision_api_key
            api_key = get_google_vision_api_key()
        except ImportError:
            # Fallback: старая логика
            api_key = os.getenv('GOOGLE_VISION_API_KEY')
            if not api_key:
                key_file = Path(__file__).parent.parent / '.google_vision_api_key'
                if not key_file.exists():
                    family_docs_key = Path.home() / "FamilyDocs" / ".google_vision_api_key"
                    if family_docs_key.exists():
                        key_file = family_docs_key
                if key_file.exists():
                    try:
                        api_key = key_file.read_text().strip()
                    except Exception:
                        pass
    
    # Используем новый парсер
    products = parse_meal_description_new(description, photo_paths, api_key)
    
    # Применяем множитель порции
    if portion_multiplier != 1.0:
        products = apply_portion_multiplier(products, portion_multiplier)
    
    return products


def calculate_nutrition(product_name: str, weight_g: float, description: str = "", basis: str = None) -> Dict[str, float]:
    """
    Рассчитывает КБЖУ для продукта с учётом basis (cooked/dry/raw).
    
    Args:
        product_name: Название продукта
        weight_g: Вес в граммах
        description: Полное описание (для определения basis)
        basis: Basis продукта (cooked/dry/raw) - если не указан, определяется автоматически
    
    Returns:
        Словарь с КБЖУ: {'calories': 120, 'protein': 23, 'fats': 3, 'carbs': 0, 'basis': 'cooked'}
    """
    from .description_parser import determine_product_basis, normalize_product_name
    
    # Определяем basis, если не указан
    if not basis:
        basis = determine_product_basis(product_name, description)

    # Нормализуем название с учётом basis
    normalized_name = normalize_product_name(product_name, basis)
    
    # Если basis = ambiguous, пробуем сначала cooked (Rule A)
    
    # Если basis = ambiguous, пробуем сначала cooked (Rule A)
    if basis == 'ambiguous':
        # Пробуем сначала как готовое
        normalized_cooked = normalize_product_name(product_name, 'cooked')
        product = find_product(normalized_cooked)
        if product:
            basis = 'cooked'
            normalized_name = normalized_cooked
        else:
            # Если не найдено готовое, пробуем сухое
            normalized_dry = normalize_product_name(product_name, 'dry')
            product = find_product(normalized_dry)
            if product:
                basis = 'dry'
                normalized_name = normalized_dry
    else:
        # Ищем продукт в базе
        product = find_product(normalized_name)
    
    if not product:
        # Пробуем поиск в интернете
        logger.info(f"Продукт '{normalized_name}' не найден в базе, ищу в интернете...")
        product = search_product_online(normalized_name)
    
    if not product:
        logger.warning(f"Продукт '{normalized_name}' не найден, использую средние значения")
        # Используем средние значения для конкретных продуктов
        default_values = {
            'яйцо': {'calories_per_100g': 143, 'protein_per_100g': 12.6, 'fats_per_100g': 9.5, 'carbs_per_100g': 0.7},
            'лук': {'calories_per_100g': 47, 'protein_per_100g': 1.4, 'fats_per_100g': 0.0, 'carbs_per_100g': 10.4},
            'томат': {'calories_per_100g': 18, 'protein_per_100g': 0.9, 'fats_per_100g': 0.2, 'carbs_per_100g': 3.9},
            'сыр': {'calories_per_100g': 363, 'protein_per_100g': 23.0, 'fats_per_100g': 30.0, 'carbs_per_100g': 0.0},
            'сливочное масло': {'calories_per_100g': 748, 'protein_per_100g': 0.5, 'fats_per_100g': 82.5, 'carbs_per_100g': 0.8},
            'морковь': {'calories_per_100g': 41, 'protein_per_100g': 0.9, 'fats_per_100g': 0.2, 'carbs_per_100g': 9.6},
            'свекла': {'calories_per_100g': 43, 'protein_per_100g': 1.6, 'fats_per_100g': 0.2, 'carbs_per_100g': 9.6},
        }
        
        # Проверяем, есть ли значения для этого продукта (используем точное совпадение слов)
        import re
        product_lower = normalized_name.lower()
        
        # Токены продукта
        product_tokens = set(re.findall(r'\w+', product_lower))
        
        for key, values in default_values.items():
            # Если ключ содержится как отдельное слово в названии продукта
            # ИЛИ если название продукта содержится как отдельное слово в ключе (редко, но бывает)
            key_tokens = set(re.findall(r'\w+', key.lower()))
            
            # Проверка 1: Ключ - это одно из слов продукта (например "сыр" в "сыр российский")
            # Но НЕ "сыр" в "сырая морковь"
            
            if any(k_token in product_tokens for k_token in key_tokens):
                 # Дополнительная проверка: для коротких ключей типа "сыр", "лук" требуем осторожности
                 # "сырая" -> tokens: ["сырая"]. "сыр" -> tokens: ["сыр"]. No match. Correct.
                 product = values
                 logger.info(f"Использованы значения по умолчанию для '{normalized_name}': {product} (match: {key})")
                 break
                 
            # Compatibility fallback (if needed? Maybe safer to just rely on product search if not exact match)
            # Let's try restrictive matching first.
        
        # Если не нашли - используем общие средние значения
        if not product:
            product = {
                'calories_per_100g': 100,
                'protein_per_100g': 10.0,
                'fats_per_100g': 5.0,
                'carbs_per_100g': 15.0,
            }
    
    # Рассчитываем КБЖУ
    multiplier = weight_g / 100.0
    
    result = {
        'calories': round(product.get('calories_per_100g', 0) * multiplier, 1),
        'protein': round(product.get('protein_per_100g', 0) * multiplier, 1),
        'fats': round(product.get('fats_per_100g', 0) * multiplier, 1),
        'carbs': round(product.get('carbs_per_100g', 0) * multiplier, 1),
        'basis': basis,
    }
    
    # Логируем, если использован cooked вместо dry (важно для отладки)
    if basis == 'cooked' and ('пшён' in product_name.lower() or 'греч' in product_name.lower() or 'рис' in product_name.lower()):
        logger.info(f"✅ Использован готовый продукт '{normalized_name}' (basis=cooked) вместо сухого для '{product_name}'")
    
    return result


def calculate_meal_totals(meal_items: List[Dict]) -> Dict[str, float]:
    """
    Рассчитывает общие КБЖУ для всех продуктов в блюде.
    
    Args:
        meal_items: Список продуктов с КБЖУ
        
    Returns:
        Словарь с общими КБЖУ
    """
    totals = {
        'calories': 0.0,
        'protein': 0.0,
        'fats': 0.0,
        'carbs': 0.0,
    }
    
    for item in meal_items:
        totals['calories'] += item.get('calories', 0)
        totals['protein'] += item.get('protein', 0)
        totals['fats'] += item.get('fats', 0)
        totals['carbs'] += item.get('carbs', 0)
    
    # Округляем
    for key in totals:
        totals[key] = round(totals[key], 1)
    
    return totals


def process_meal_description(
    description: str,
    photo_paths: Optional[List[Path]] = None,
    portion_multiplier: float = 1.0,
    api_key: Optional[str] = None
) -> Tuple[List[Dict], Dict[str, float]]:
    """
    Полный цикл обработки описания блюда:
    1. Парсит описание и извлекает продукты
    2. Рассчитывает КБЖУ для каждого продукта
    3. Возвращает список продуктов и общие КБЖУ
    
    Args:
        description: Описание блюда
        photo_paths: Список путей к фото (опционально)
        portion_multiplier: Множитель порции
        api_key: API ключ Google Cloud Vision (опционально)
        
    Returns:
        Кортеж (meal_items, meal_totals):
        - meal_items: список продуктов с КБЖУ
        - meal_totals: общие КБЖУ
    """
    # Парсим описание
    products = parse_meal_description(description, photo_paths, api_key, portion_multiplier)
    
    # 1. СНАЧАЛА проверяем явные итоги в описании (MAX PRIORITY)
    from .description_parser import extract_explicit_totals
    explicit_totals = extract_explicit_totals(description)
    
    # Рассчитываем КБЖУ для каждого продукта
    meal_items = []
    
    # Флаг, что мы используем ручные итоги
    using_manual_totals = False
    
    # Если есть явные итоги - используем их для общих значений
    if explicit_totals:
        logger.info(f"✅ Найдены явные КБЖУ в описании: {explicit_totals}")
        using_manual_totals = True
        
    for product in products:
        # Если это меню с уже готовыми КБЖУ - используем их
        if product.get('source') == 'menu_ocr' and product.get('menu_data'):
            menu_data = product.get('menu_data', {})
            print(f"    ✅ Используем КБЖУ из меню: {menu_data.get('calories')} ккал, "
                  f"Б: {menu_data.get('protein')}г, Ж: {menu_data.get('fats')}г, У: {menu_data.get('carbs')}г")
            meal_items.append({
                'product': product['name'],
                'weight_g': product.get('weight'),
                'weight_source': 'menu',
                'weight_estimated': False,
                'calories': menu_data.get('calories', 0),
                'protein': menu_data.get('protein', 0),
                'fats': menu_data.get('fats', 0),
                'carbs': menu_data.get('carbs', 0),
                'source': 'menu_ocr',
            })
        # Если есть готовые КБЖУ напрямую в продукте (из parse_meal_description)
        # Проверяем source='menu_ocr' ИЛИ наличие calories без weight (это меню)
        elif (product.get('calories') is not None and 
              (product.get('source') == 'menu_ocr' or 
               (product.get('weight') is None and product.get('calories', 0) > 0))):
            print(f"    ✅ Используем КБЖУ из меню (прямо в продукте): {product.get('calories')} ккал, "
                  f"Б: {product.get('protein')}г, Ж: {product.get('fats')}г, У: {product.get('carbs')}г")
            meal_items.append({
                'product': product['name'],
                'weight_g': product.get('weight'),
                'weight_source': 'menu',
                'weight_estimated': False,
                'calories': product.get('calories', 0),
                'protein': product.get('protein', 0),
                'fats': product.get('fats', 0),
                'carbs': product.get('carbs', 0),
                'source': 'menu_ocr',
            })
        elif product.get('weight') and product['weight'] > 0:
            # Передаём description для определения basis
            nutrition = calculate_nutrition(
                product['name'], 
                product['weight'],
                description=description,
                basis=product.get('basis')  # Если basis уже определён в продукте
            )
            
            meal_items.append({
                'product': product['name'],
                'weight_g': round(product['weight'], 2),
                'weight_source': product.get('source', 'unknown'),
                'weight_estimated': product.get('source') in ['portion_estimate', 'default_portion'],
                'calories': nutrition['calories'],
                'protein': nutrition['protein'],
                'fats': nutrition['fats'],
                'carbs': nutrition['carbs'],
                'basis': nutrition.get('basis', 'raw'),  # Сохраняем basis
                'source': 'local_db',  # или 'online_search' если искали в интернете
            })
        elif product.get('source') == 'description_simple':
            # Для простых описаний (кофе, чай) используем стандартную порцию
            # Например, кофе - 250мл, чай - 250мл
            default_weights = {
                'кофе': 250,  # мл
                'чай': 250,   # мл
                'сок': 200,   # мл
                'вода': 250,  # мл
                'молоко': 250,  # мл
            }
            product_name_lower = product['name'].lower()
            default_weight = default_weights.get(product_name_lower, 100)
            
            nutrition = calculate_nutrition(product['name'], default_weight)
            
            meal_items.append({
                'product': product['name'],
                'weight_g': default_weight,
                'weight_source': 'default_portion',
                'weight_estimated': True,
                'calories': nutrition['calories'],
                'protein': nutrition['protein'],
                'fats': nutrition['fats'],
                'carbs': nutrition['carbs'],
                'source': 'local_db',
            })
    
    # Рассчитываем общие КБЖУ
    meal_totals = calculate_meal_totals(meal_items)
    
    # Если найдены явные итоги - заменяем общие значения
    if using_manual_totals and explicit_totals:
        if 'calories' in explicit_totals:
            meal_totals['calories'] = explicit_totals['calories']
        if 'protein' in explicit_totals:
            meal_totals['protein'] = explicit_totals['protein']
        if 'fats' in explicit_totals:
            meal_totals['fats'] = explicit_totals['fats']
        if 'carbs' in explicit_totals:
            meal_totals['carbs'] = explicit_totals['carbs']
            
    return meal_items, meal_totals


# Реэкспорт вынесенных функций для обратной совместимости
from .llm_food_processor import process_llm_food_data  # noqa: F401
from .menu_meal_processor import process_meal_description_with_menu  # noqa: F401

# Сохраняем старую функцию для обратной совместимости
def extract_weight_from_photo_legacy(photo_path: Path, api_key: Optional[str] = None) -> Optional[float]:
    """
    Старая функция для обратной совместимости.
    Использует новый модуль weight_extraction.
    """
    return extract_weight_from_photo(photo_path, api_key)


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
            from .description_parser import extract_products_from_description, normalize_product_name
            regex_products = extract_products_from_description(description)
            for p in regex_products:
                if p.get('weight'):
                    # Map normalized name to weight
                    # Use simple normalization
                    n_name = normalize_product_name(p['name'])
                    regex_items_map[n_name] = p['weight']
                    # Also map raw name just in case
                    regex_items_map[p['name'].lower()] = p['weight']
        except Exception as e:
            print(f"Error in regex fallback: {e}")

    for item in items:
        logger.info(f"🔍 Processing LLM item: {item}")
        name = item.get('name', 'Unknown')
        weight = item.get('weight')
        
        # Приоритет: вес из описания пользователя (regex). LLM мог ошибиться или default перезаписать.
        regex_matched = False
        if description:
            from .description_parser import normalize_product_name
            n_name = normalize_product_name(name)
            regex_weight = None
            if n_name in regex_items_map:
                regex_weight = regex_items_map[n_name]
            elif name.lower() in regex_items_map:
                regex_weight = regex_items_map[name.lower()]
            if not regex_weight:
                name_tokens = set(name.lower().split())
                for r_name, r_weight in regex_items_map.items():
                    r_tokens = set(r_name.split())
                    if len(name_tokens & r_tokens) >= 1 and len(r_name) > 3 and len(name) > 3:
                        regex_weight = r_weight
                        break
            if regex_weight is not None:
                weight = regex_weight
                regex_matched = True
        
        # Только если пользователь НЕ указал вес явно — используем default для бутылок/порций
        # Иначе "100г пельменей" перезаписывалось бы на 250г стандартной порции
        if not regex_matched:
            from .description_parser import get_default_unit_weight
            default_weight = get_default_unit_weight(name)
            if default_weight > 0 and (not weight or weight < default_weight * 0.5):
                weight = default_weight
        
        # Fallback: если regex не сработал — default_weight уже применили выше
        
        # Custom Logic: Prioritize Database Lookup over LLM macros
        # Даже если LLM вернул макросы, проверяем базу данных, так как там могут быть
        # более точные/любимые продукты пользователя (например, Bombbar)
        from .description_parser import normalize_product_name
        
        # Нормализуем имя для поиска
        norm_name = normalize_product_name(name)
        
        # Пытаемся распарсить quantity если нет веса
        if (not weight or weight == 0) and item.get('quantity'):
            qty_str = str(item.get('quantity')).lower().strip()
            import re
            
            # Миллилитры (1 мл = 1 г приближенно для напитков)
            ml_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:мл|ml|milliliter)', qty_str)
            if ml_match:
                try:
                    weight = float(ml_match.group(1).replace(',', '.'))
                    weight_src = 'quantity_ml'
                except ValueError:
                    pass
                    
            # Литры
            l_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:л|l|liter)', qty_str)
            if l_match:
                try:
                    weight = float(l_match.group(1).replace(',', '.')) * 1000
                    weight_src = 'quantity_l'
                except ValueError:
                    pass
                    
            # Граммы
            g_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:г|g|gram)', qty_str)
            if g_match:
                try:
                    weight = float(g_match.group(1).replace(',', '.'))
                    weight_src = 'quantity_g'
                except ValueError:
                    pass
                    
            # Килограммы
            kg_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:кг|kg|kilogram)', qty_str)
            if kg_match:
                try:
                    weight = float(kg_match.group(1).replace(',', '.')) * 1000
                    weight_src = 'quantity_kg'
                except ValueError:
                    pass

        db_product = find_product(norm_name)
        if not db_product:
            # Пробуем без нормализации или lowercase
            db_product = find_product(name)
            
        if db_product:
            logger.info(f"✅ Product found in DB (overriding LLM): {name}")
            
            # Определяем вес
            final_weight = weight
            weight_src = 'llm'
            
            if not final_weight:
                # Если вес не указан, берем дефолтный вес из базы (если есть) или оцениваем
                final_weight = db_product.get('weight_g')
                if final_weight:
                   weight_src = 'db_default'
                else:
                   # Оценка веса
                   from .description_parser import get_default_unit_weight
                   try:
                       qty = float(item.get('quantity', 1))
                   except (ValueError, TypeError):
                       qty = 1.0
                   if not qty or qty <= 0: qty = 1.0
                   
                   unit_weight = get_default_unit_weight(name)
                   if unit_weight > 0:
                       final_weight = unit_weight * qty
                       weight_src = 'estimate'
            
            # Если веса все еще нет, ставим 100г для расчета (но помечаем?)
            # Нет, если веса нет, мы не можем добавить продукт корректно в лог с весом.
            # Но мы можем добавить его с весом 0 или None?
            if not final_weight:
                 logger.warning(f"Product {name} found in DB but no weight determined. Using 100g default.")
                 final_weight = 100.0
                 weight_src = 'default_100g'

            # Рассчитываем макросы на основе веса и данных БД
            # Данные в БД хранятся на 100г
            multiplier = final_weight / 100.0
            
            meal_items.append({
                'product': db_product.get('name', name), # Используем имя из БД (оно может быть красивее)
                'weight_g': final_weight,
                'weight_source': weight_src,
                'calories': round(db_product.get('calories_per_100g', 0) * multiplier, 1),
                'protein': round(db_product.get('protein_per_100g', 0) * multiplier, 1),
                'fats': round(db_product.get('fats_per_100g', 0) * multiplier, 1),
                'carbs': round(db_product.get('carbs_per_100g', 0) * multiplier, 1),
                'source': 'local_db_priority', # Mark as DB source
                'note': db_product.get('note')
            })
            # Skip checking LLM macros if DB found
            continue
        
        # ORIGINAL LOGIC
        has_macros = item.get('calories') is not None and item.get('calories') > 0
        
        # Защита от галлюцинаций LLM (максимум ~900 ккал/100г для чистого жира)
        if has_macros and weight and weight > 0:
            cal_per_100g = (item['calories'] / weight) * 100
            if cal_per_100g > 1000:
                logger.warning(f"⚠️ LLM сгаллюцинировал макросы для '{name}'! {item['calories']} ккал на {weight}г ({cal_per_100g} ккал/100г). Игнорируем.")
                has_macros = False
        
        if has_macros:
            # Если вес не указан, но есть калории - пробуем оценить вес по названию (для отображения)
            final_weight = weight
            weight_src = 'llm'
            
            if not final_weight:
                from .description_parser import get_default_unit_weight
                # Если LLM вернул quantity, используем его
                try:
                    qty = float(item.get('quantity', 1))
                except (ValueError, TypeError):
                    qty = 1.0
                
                # Если quantity=0 или None, считаем 1 (для штучных товаров)
                if not qty or qty <= 0:
                    qty = 1.0
                    
                unit_weight = get_default_unit_weight(name)
                if unit_weight > 0:
                    final_weight = unit_weight * qty
                    weight_src = 'estimate'
            
            # Напитки без калорий: LLM часто путает с обычной колой
            if is_zero_calorie_drink(name):
                cal, prot, fat, carb = 0.0, 0.0, 0.0, 0.0
                src = 'llm_router_zero_drink'
            else:
                cal = float(item.get('calories') or 0)
                prot = float(item.get('protein') or 0)
                fat = float(item.get('fats') or 0)
                carb = float(item.get('carbs') or 0)
                src = 'llm_router'
                    
            meal_items.append({
                'product': name,
                'weight_g': final_weight,
                'weight_source': weight_src,
                'calories': cal,
                'protein': prot,
                'fats': fat,
                'carbs': carb,
                'source': src,
            })
        elif weight and weight > 0:
            # Calculate using local DB (или 0 для напитков без калорий)
            if is_zero_calorie_drink(name):
                meal_items.append({
                    'product': name,
                    'weight_g': weight,
                    'weight_source': 'llm',
                    'calories': 0.0, 'protein': 0.0, 'fats': 0.0, 'carbs': 0.0,
                    'source': 'llm_router_zero_drink',
                })
            else:
                nutrition = calculate_nutrition(name, weight)
                cal = nutrition['calories']
                prot = nutrition['protein']
                fat = nutrition['fats']
                carb = nutrition['carbs']
                # БД не знает блюдо — даём грубую оценку (~100–150 ккал/100г для салатов/готовых блюд)
                if cal == 0 and not is_zero_calorie_drink(name):
                    cal = round(weight * 0.12, 1)   # ~120 ккал/100г
                    prot = round(weight * 0.03, 1)
                    fat = round(weight * 0.06, 1)
                    carb = round(weight * 0.12, 1)
                    nutrition = {**nutrition, 'calories': cal, 'protein': prot, 'fats': fat, 'carbs': carb}
                meal_items.append({
                    'product': name,
                    'weight_g': weight,
                    'weight_source': 'llm',
                    'calories': nutrition['calories'],
                    'protein': nutrition['protein'],
                    'fats': nutrition['fats'],
                    'carbs': nutrition['carbs'],
                    'basis': nutrition.get('basis', 'raw'),
                    'source': 'local_db'
                })
        else:
            # 3. No weight, no macros. Try to estimate!
            from .description_parser import get_default_unit_weight
            try:
                qty = float(item.get('quantity', 1))
            except (ValueError, TypeError):
                qty = 1.0
                
            if not qty or qty <= 0: qty = 1.0
            
            # Напитки без калорий — не применять грубую оценку
            if is_zero_calorie_drink(name):
                unit_weight = get_default_unit_weight(name) or 330.0  # банка
                estimated_weight = unit_weight * qty
                meal_items.append({
                    'product': name,
                    'weight_g': estimated_weight,
                    'weight_source': 'estimate',
                    'weight_estimated': True,
                    'calories': 0.0, 'protein': 0.0, 'fats': 0.0, 'carbs': 0.0,
                    'source': 'llm_router_zero_drink',
                })
                continue
            
            unit_weight = get_default_unit_weight(name)
            
            if unit_weight > 0:
                estimated_weight = unit_weight * qty
                nutrition = calculate_nutrition(name, estimated_weight)
                
                # Если продукта нет в локальной БД, попробуем данные LLM
                cal = nutrition['calories']
                prot = nutrition['protein']
                fat = nutrition['fats']
                carb = nutrition['carbs']
                source = 'local_db_estimate'
                
                if cal == 0:
                    # Локальная БД не знает этот продукт — сделаем грубую оценку
                    # (~150 ккал на 100г для среднего готового блюда)
                    cal = round(estimated_weight * 1.5, 1)
                    prot = round(estimated_weight * 0.08, 1)
                    fat = round(estimated_weight * 0.06, 1) 
                    carb = round(estimated_weight * 0.12, 1)
                    source = 'rough_estimate'
                    logger.info(f"⚠️ Rough estimate for '{name}' ({estimated_weight}g): {cal} kcal")
                
                meal_items.append({
                    'product': name,
                    'weight_g': estimated_weight,
                    'weight_source': 'estimate',
                    'weight_estimated': True,
                    'calories': cal,
                    'protein': prot,
                    'fats': fat,
                    'carbs': carb,
                    'source': source
                })
            else:
                # Совсем не знаем вес — берём 200г как стандартную порцию
                estimated_weight = 200.0
                cal = round(estimated_weight * 1.5, 1)
                prot = round(estimated_weight * 0.08, 1)
                fat = round(estimated_weight * 0.06, 1)
                carb = round(estimated_weight * 0.12, 1)
                logger.info(f"⚠️ Default portion estimate for '{name}': {estimated_weight}g, {cal} kcal")
                
                meal_items.append({
                    'product': name,
                    'weight_g': estimated_weight,
                    'weight_source': 'default_portion',
                    'weight_estimated': True,
                    'calories': cal,
                    'protein': prot,
                    'fats': fat,
                    'carbs': carb,
                    'source': 'rough_estimate'
                })
            
    
    # Check for explicit total_nutrition from LLM (Recipe Cards/Labels)
    total_nutrition = data.get('total_nutrition')
    
    # Calculate totals from items first (as baseline)
    computed_totals = calculate_meal_totals(meal_items)
    
    # ТОЛЬКО для рецептурных карточек (1 продукт с явной этикеткой питания),
    # НЕ для списков блюд (где LLM может вернуть total_nutrition только для последнего продукта)
    dish_name = data.get('dish_name', '')
    first_product = meal_items[0].get('product', '') if meal_items else ''
    if total_nutrition and (total_nutrition.get('calories') or 0) > 0:
        if len(meal_items) == 1 and is_zero_calorie_drink(dish_name or first_product):
            return meal_items, {'calories': 0.0, 'protein': 0.0, 'fats': 0.0, 'carbs': 0.0}
        if len(meal_items) == 1:
            # Один продукт с явной этикеткой - используем total_nutrition
            logger.info(f"✅ Using explicit total nutrition from LLM (Recipe/Label): {total_nutrition}")
            return meal_items, {
                'calories': float(total_nutrition.get('calories', 0)),
                'protein': float(total_nutrition.get('protein', 0)),
                'fats': float(total_nutrition.get('fats', 0)),
                'carbs': float(total_nutrition.get('carbs', 0))
            }
        else:
            # Список блюд - игнорируем total_nutrition, используем вычисленную сумму
            logger.info(f"⚠️  Ignoring total_nutrition for multi-item meal (len={len(meal_items)}), using computed totals: {computed_totals}")

    return meal_items, computed_totals
