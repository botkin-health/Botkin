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
    normalize_product_name
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


def process_meal_description_with_menu(
    description: str,
    menu_data: Dict,
    photo_paths: Optional[List[Path]] = None,
    portion_multiplier: float = 1.0,
    api_key: Optional[str] = None
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
    import re
    
    # Парсим описание БЕЗ распознавания меню из фото
    # (чтобы не потерять дополнительные продукты из описания)
    # Используем напрямую парсер описания
    from .description_parser import extract_products_from_description
    
    # Инициализируем products пустым списком
    products = []
    
    # Если в menu_data есть компоненты (от ChatGPT), используем их!
    # Это приоритетный источник, так как ИИ уже разбил блюдо на части
    if menu_data and menu_data.get('components'):
        logger.info(f"✅ Найдено {len(menu_data['components'])} компонентов от ИИ. Используем их вместо парсинга описания.")
        products = []
        for comp in menu_data['components']:
            products.append({
                'name': comp.get('name'),
                'weight': comp.get('weight'),
                'calories': comp.get('calories'),
                'protein': comp.get('protein'),
                'fats': comp.get('fats'),
                'carbs': comp.get('carbs'),
                'source': 'menu_ocr_component',
                'menu_data': menu_data # Ссылка на родителя
            })
            
    # Если компонентов нет, парсим описание
    if not products:
        # Извлекаем продукты из описания
        products = extract_products_from_description(description)
    
    # Если продукты не найдены в описании, но есть данные меню - используем их
    if not products and menu_data:
        dish_name = menu_data.get('dish_name', 'Блюдо из меню')
        # Проверяем, что описание не содержит явного отказа (хотя это сложно)
        # Просто добавляем блюдо из меню
        logger.info(f"В описании не найдено продуктов, добавляем блюдо из меню: {dish_name}")
        products = [{
            'name': dish_name,
            'weight': None,
            'source': 'menu_ocr'
        }]
    
    # Применяем множитель порции ТОЛЬКО если продукты НЕ из menu_data
    # Если продукты из menu_data, ChatGPT уже учитывает порцию из описания (например "1/2 пиццы")
    # и возвращает КБЖУ и вес уже для этой порции
    products_from_menu = any(p.get('source') in ('menu_ocr', 'menu_ocr_component') for p in products)
    if portion_multiplier != 1.0 and not products_from_menu:
        from .description_parser import apply_portion_multiplier
        products = apply_portion_multiplier(products, portion_multiplier)
    
    # Получаем название блюда из меню
    # Используем полное название, включая все возможные варианты
    menu_dish_name = menu_data.get('dish_name', '').lower()
    
    # Также проверяем, есть ли в menu_data дополнительные поля с информацией о продукте
    # (например, если ChatGPT вернул более детальную информацию)
    menu_full_text = menu_dish_name  # Можно расширить, если есть другие поля
    
    # КБЖУ из меню (обычно на 100г)
    # Если есть nutrition_per_100g, используем его (это исходные значения на 100г)
    # Иначе используем значения из menu_data (могут быть пересчитаны на вес порции)
    nutrition_per_100g = menu_data.get('nutrition_per_100g', {})
    if nutrition_per_100g:
        menu_calories_per_100g = nutrition_per_100g.get('calories') or 0
        menu_protein_per_100g = nutrition_per_100g.get('protein') or 0
        menu_fats_per_100g = nutrition_per_100g.get('fats') or 0
        menu_carbs_per_100g = nutrition_per_100g.get('carbs') or 0
    else:
        # Если нет nutrition_per_100g, используем значения из menu_data
        # Но нужно проверить, не пересчитаны ли они уже на вес порции
        menu_weight = menu_data.get('weight')
        if menu_weight and menu_weight > 0:
            # Если есть вес порции, возможно значения уже пересчитаны
            # Пересчитываем обратно на 100г
            multiplier = 100.0 / menu_weight
            menu_calories_per_100g = (menu_data.get('calories') or 0) * multiplier
            menu_protein_per_100g = (menu_data.get('protein') or 0) * multiplier
            menu_fats_per_100g = (menu_data.get('fats') or 0) * multiplier
            menu_carbs_per_100g = (menu_data.get('carbs') or 0) * multiplier
        else:
            # Нет веса порции, считаем что значения на 100г
            menu_calories_per_100g = menu_data.get('calories') or 0
            menu_protein_per_100g = menu_data.get('protein') or 0
            menu_fats_per_100g = menu_data.get('fats') or 0
            menu_carbs_per_100g = menu_data.get('carbs') or 0
    
    # Вес из меню (если указан)
    menu_weight = menu_data.get('weight')
    
    meal_items = []
    
    # Обрабатываем каждый продукт из описания
    # Убираем дубликаты продуктов (по нормализованному названию и весу)
    from .description_parser import normalize_product_name
    seen_products = set()
    unique_products = []
    for product in products:
        # Нормализуем название для сравнения (убираем окончания, лишние слова)
        product_name = product.get('name', '').lower().strip()
        # Убираем окончания типа "переку", "перекус" и т.д.
        product_name_clean = re.sub(r'\s*(переку|перекус|обед|завтрак|ужин|бранч|полдник)\s*$', '', product_name)
        # Нормализуем через функцию нормализации
        normalized_name = normalize_product_name(product_name_clean)
        product_weight = product.get('weight') or 0
        
        # Дополнительная нормализация для картошки (убираем разные окончания)
        # "варенной картошки" и "варенной картошк" должны стать одинаковыми
        if 'картош' in normalized_name or 'картофел' in normalized_name:
            # Приводим к единому виду
            if 'варен' in normalized_name or 'отварн' in normalized_name:
                normalized_name = 'картофель отварной'
            elif 'жарен' in normalized_name:
                normalized_name = 'картофель жареный'
            elif 'печен' in normalized_name or 'запечен' in normalized_name:
                normalized_name = 'картофель запечённый'
            else:
                normalized_name = 'картофель'
        
        # Создаем ключ для сравнения
        product_key = (normalized_name, round(product_weight, 1))
        
        if product_key not in seen_products:
            seen_products.add(product_key)
            # Обновляем название продукта на нормализованное
            product['name'] = normalized_name
            unique_products.append(product)
        else:
            logger.info(f"  ⚠️  Пропущен дубликат: '{product_name}' (нормализовано: '{normalized_name}', вес: {product_weight}г)")
    products = unique_products
    
    logger.info(f"Обработка {len(products)} продуктов с учетом меню: {menu_dish_name}")
    logger.info(f"КБЖУ из меню (на 100г): {menu_calories_per_100g} ккал, Б: {menu_protein_per_100g}г, Ж: {menu_fats_per_100g}г, У: {menu_carbs_per_100g}г")
    
    for product in products:
        product_name = product.get('name', '').lower()
        product_weight = product.get('weight')
        
        logger.info(f"Проверка продукта: '{product_name}' (вес: {product_weight}г)")
        
        # Проверяем, соответствует ли продукт блюду из меню
        # Сравниваем по ключевым словам (например, "угорь" в меню и "угря" в описании)
        # Убираем стоп-слова и короткие слова
        stop_words = {'в', 'на', 'с', 'из', 'для', 'и', 'или', 'как', 'что', 'это', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'with', 'калининградский', 'кусок', 'соус', 'унаги', 'стерилизованные', 'консервы'}
        menu_keywords = {w for w in re.findall(r'\b\w+\b', menu_dish_name) if len(w) > 2 and w not in stop_words}
        product_keywords = {w for w in re.findall(r'\b\w+\b', product_name) if len(w) > 2 and w not in stop_words}
        
        logger.info(f"  Ключевые слова меню: {menu_keywords}")
        logger.info(f"  Ключевые слова продукта: {product_keywords}")
        
        # Словарь для сопоставления видов рыбы (в разных падежах)
        fish_variants = {
            'угорь': ['угря', 'угря', 'угрем', 'угре'],
            'лосось': ['лосося', 'лососем', 'лососе'],
            'тунец': ['тунца', 'тунцом', 'тунце'],
            'сельдь': ['сельди', 'сельдью', 'сельди'],
            'скумбрия': ['скумбрии', 'скумбрией', 'скумбрии'],
            'сардина': ['сардины', 'сардиной', 'сардине'],
        }
        
        # Проверяем, является ли продукт рыбой из меню
        # Если в меню есть "рыбные" или "консервы", а продукт - это рыба
        is_fish_product = False
        fish_name_in_menu = None
        fish_name_in_product = None
        
        # Проверяем, есть ли в меню название рыбы
        for fish_base, fish_forms in fish_variants.items():
            if fish_base in menu_dish_name or any(form in menu_dish_name for form in fish_forms):
                fish_name_in_menu = fish_base
                break
        
        # Проверяем, является ли продукт этой рыбой
        for fish_base, fish_forms in fish_variants.items():
            if fish_base in product_name or any(form in product_name for form in fish_forms):
                fish_name_in_product = fish_base
                if fish_name_in_menu and fish_name_in_product == fish_name_in_menu:
                    is_fish_product = True
                    logger.info(f"  ✅ Найдено соответствие: рыба '{fish_name_in_product}' в меню и продукте")
                break
        
        # Если в меню есть "рыбные" или "консервы", а продукт - это рыба (любая)
        if not is_fish_product:
            if ('рыбные' in menu_dish_name or 'консервы' in menu_dish_name) and fish_name_in_product:
                # Проверяем, что в описании упоминается эта рыба рядом с весом
                description_lower = description.lower()
                for fish_base, fish_forms in fish_variants.items():
                    if fish_base == fish_name_in_product or any(form == fish_name_in_product for form in fish_forms):
                        # Ищем паттерн "вес + рыба" или "рыба + вес"
                        pattern = rf'\d+\s*(?:г|грамм|g)\s+.*?(?:{fish_base}|{"|".join(fish_forms)})|(?:{fish_base}|{"|".join(fish_forms)}).*?\d+\s*(?:г|грамм|g)'
                        if re.search(pattern, description_lower):
                            is_fish_product = True
                            logger.info(f"  ✅ Найдено соответствие: 'рыбные консервы' в меню и '{fish_name_in_product}' в описании")
                            break
        
        # Если есть пересечение ключевых слов (хотя бы 1 значимое слово совпадает)
        # ИЛИ если название продукта содержит название блюда из меню
        # ИЛИ если это рыба из рыбных консервов
        is_menu_product = (
            product.get('source') == 'menu_ocr_component' or
            is_fish_product or
            len(menu_keywords & product_keywords) > 0 or
            any(keyword in product_name for keyword in menu_keywords if len(keyword) > 3) or
            any(keyword in menu_dish_name for keyword in product_keywords if len(keyword) > 3)
        )
        
        # Дополнительная проверка: если в описании есть упоминание продукта из меню
        # (например, "угорь" в меню и "угря" в описании)
        if not is_menu_product:
            # Проверяем, содержит ли описание ключевые слова из меню
            description_lower = description.lower()
            for keyword in menu_keywords:
                if len(keyword) > 3:
                    # Проверяем, что этот продукт упоминается рядом с весом
                    # (например, "50 грамм угря" или "угря 50 грамм")
                    pattern = rf'\d+\s*(?:г|грамм|g)\s+.*?{re.escape(keyword)}|{re.escape(keyword)}.*?\d+\s*(?:г|грамм|g)'
                    if re.search(pattern, description_lower):
                        # Также проверяем, что название продукта содержит это ключевое слово
                        if keyword in product_name:
                            is_menu_product = True
                            logger.info(f"  ✅ Найдено соответствие по ключевому слову '{keyword}' в описании")
                            break
        
        if is_menu_product:
            logger.info(f"  ✅ Продукт '{product_name}' соответствует меню")
            
            # Если у продукта уже есть свои КБЖУ (от ChatGPT components), используем их!
            if product.get('source') == 'menu_ocr_component' and product.get('calories') is not None:
                 logger.info(f"  ✅ Используем собственные КБЖУ компонента (не пересчитываем от общего меню):")
                 logger.info(f"    {product.get('calories')} ккал, {product.get('protein')}г б, {product.get('fats')}г ж, {product.get('carbs')}г у")
                 
                 meal_items.append({
                    'product': product.get('name', menu_data.get('dish_name', 'Продукт из меню')),
                    'weight_g': round(product_weight, 2) if product_weight else None,
                    'weight_source': 'description',
                    'weight_estimated': False,
                    'calories': round(product.get('calories', 0), 1),
                    'protein': round(product.get('protein', 0), 1),
                    'fats': round(product.get('fats', 0), 1),
                    'carbs': round(product.get('carbs', 0), 1),
                    'source': 'menu_ocr_component',
                })

            elif product_weight and product_weight > 0:
                # Это продукт из меню с указанным весом - пересчитываем КБЖУ
                # КБЖУ из меню обычно на 100г, пересчитываем на указанный вес
                multiplier = product_weight / 100.0
                
                calories = menu_calories_per_100g * multiplier
                protein = menu_protein_per_100g * multiplier
                fats = menu_fats_per_100g * multiplier
                carbs = menu_carbs_per_100g * multiplier
                
                logger.info(f"  Пересчитано КБЖУ из меню для {product_weight}г:")
                logger.info(f"    {menu_calories_per_100g} ккал/100г × {multiplier:.2f} = {calories:.1f} ккал")
                logger.info(f"    {menu_protein_per_100g}г белка/100г × {multiplier:.2f} = {protein:.1f}г")
                logger.info(f"    {menu_fats_per_100g}г жиров/100г × {multiplier:.2f} = {fats:.1f}г")
                logger.info(f"    {menu_carbs_per_100g}г углеводов/100г × {multiplier:.2f} = {carbs:.1f}г")
            
                meal_items.append({
                    'product': product.get('name', menu_data.get('dish_name', 'Продукт из меню')),
                    'weight_g': round(product_weight, 2),
                    'weight_source': 'description',
                    'weight_estimated': False,
                    'calories': round(calories, 1),
                    'protein': round(protein, 1),
                    'fats': round(fats, 1),
                    'carbs': round(carbs, 1),
                    'source': 'menu_ocr',
                })
            else:
                # Это продукт из меню, но вес не указан - используем вес из меню или 100г по умолчанию
                weight_to_use = menu_weight if menu_weight else 100.0
                
                meal_items.append({
                    'product': product.get('name', menu_data.get('dish_name', 'Продукт из меню')),
                    'weight_g': weight_to_use,
                    'weight_source': 'menu',
                    'weight_estimated': False,
                    'calories': menu_calories_per_100g * (weight_to_use / 100.0),
                    'protein': menu_protein_per_100g * (weight_to_use / 100.0),
                    'fats': menu_fats_per_100g * (weight_to_use / 100.0),
                    'carbs': menu_carbs_per_100g * (weight_to_use / 100.0),
                    'source': 'menu_ocr',
                })
        else:
            # Это дополнительный продукт (не из меню) - обрабатываем как обычно
            logger.info(f"  ❌ Продукт '{product_name}' НЕ соответствует меню, обрабатываем как обычный продукт")
            if product.get('weight') and product['weight'] > 0:
                nutrition = calculate_nutrition(
                    product['name'], 
                    product['weight'],
                    description=description,
                    basis=product.get('basis')
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
                    'basis': nutrition.get('basis', 'raw'),
                    'source': 'local_db',
                })
            elif product.get('source') == 'description_simple':
                default_weights = {
                    'кофе': 250,
                    'чай': 250,
                    'сок': 200,
                    'вода': 250,
                    'молоко': 250,
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
    
    return meal_items, meal_totals


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
        name = item.get('name', 'Unknown')
        weight = item.get('weight')
        
        # Fallback: Try to find weight in regex results if missing
        if not weight and description:
            from .description_parser import normalize_product_name
            n_name = normalize_product_name(name)
            if n_name in regex_items_map:
                weight = regex_items_map[n_name]
            elif name.lower() in regex_items_map:
                weight = regex_items_map[name.lower()]
            
            # Additional fuzzy search?
            # If "подсолнечное масло" (LLM) vs "масло подсолнечное" (Regex)
            # Simple token overlap check
            if not weight:
                name_tokens = set(name.lower().split())
                for r_name, r_weight in regex_items_map.items():
                   r_tokens = set(r_name.split())
                   # If significant overlap (e.g. "maslo" in both)
                   if len(name_tokens & r_tokens) >= 1 and len(r_name) > 3 and len(name) > 3:
                       # Be careful not to mix "oil" and "butter" if they have differenet weights?
                       # But here we just want to rescue missing weights.
                       weight = r_weight
                       break
        
        # If LLM gave full macros, trust them (but prefer local calculation if weight is known to ensure consistency? 
        # No, trust LLM if it saw the photo/text, it might be a specific product. 
        # But if macros are 0/missing, use calculate_nutrition).
        
        has_macros = item.get('calories') is not None and item.get('calories') > 0
        
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
                    
            meal_items.append({
                'product': name,
                'weight_g': final_weight,
                'weight_source': weight_src,
                'calories': float(item.get('calories') or 0),
                'protein': float(item.get('protein') or 0),
                'fats': float(item.get('fats') or 0),
                'carbs': float(item.get('carbs') or 0),
                'source': 'llm_router'
            })
        elif weight and weight > 0:
            # Calculate using local DB
            nutrition = calculate_nutrition(name, weight)
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
            
            unit_weight = get_default_unit_weight(name)
            
            if unit_weight > 0:
                estimated_weight = unit_weight * qty
                nutrition = calculate_nutrition(name, estimated_weight)
                
                meal_items.append({
                    'product': name,
                    'weight_g': estimated_weight,
                    'weight_source': 'estimate',
                    'weight_estimated': True,
                    'calories': nutrition['calories'],
                    'protein': nutrition['protein'],
                    'fats': nutrition['fats'],
                    'carbs': nutrition['carbs'],
                    'source': 'local_db_estimate'
                })
            else:
                # Fallback: just list it without weight
                meal_items.append({
                    'product': name,
                    'weight_g': None,
                    'weight_source': 'unknown',
                    'calories': 0,
                    'protein': 0,
                    'fats': 0,
                    'carbs': 0,
                    'source': 'unknown'
                })
            
    totals = calculate_meal_totals(meal_items)
    return meal_items, totals
