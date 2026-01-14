#!/usr/bin/env python3
"""
Поиск продуктов в базе данных и онлайн
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
import requests
import os
import time

try:
    from .chatgpt_vision import get_openai_api_key
except ImportError:
    # Фолбек
    def get_openai_api_key():
        return os.getenv('OPENAI_API_KEY')

logger = logging.getLogger(__name__)

# Путь к базе продуктов
PRODUCTS_DB_PATH = Path(__file__).parent.parent / 'data' / 'products.json'
if not PRODUCTS_DB_PATH.exists():
    # Пробуем альтернативные пути
    alt_paths = [
        Path(__file__).parent.parent.parent / 'data' / 'products.json',
        Path(__file__).parent.parent / 'products.json',
    ]
    for alt_path in alt_paths:
        if alt_path.exists():
            PRODUCTS_DB_PATH = alt_path
            break


def load_products_db() -> Dict:
    """
    Загружает базу продуктов из JSON файла.
    
    Returns:
        Словарь с продуктами или пустой словарь, если файл не найден
    """
    if not PRODUCTS_DB_PATH.exists():
        logger.warning(f"База продуктов не найдена: {PRODUCTS_DB_PATH}")
        return {}
    
    try:
        with open(PRODUCTS_DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Поддерживаем разные форматы
            if 'products' in data:
                return data['products']
            return data
    except Exception as e:
        logger.error(f"Ошибка при загрузке базы продуктов: {e}")
        return {}


def save_product_to_db(name: str, product_data: Dict) -> None:
    """Сохраняет новый продукт в products.json"""
    try:
        # Сначала нормализуем название
        key = name.lower().strip()
        
        # Читаем файл
        if PRODUCTS_DB_PATH.exists():
            with open(PRODUCTS_DB_PATH, 'r', encoding='utf-8') as f:
                full_data = json.load(f)
        else:
            full_data = {"products": {}}

        # Структура может быть просто dict или {"products": dict}
        if "products" in full_data:
            products_map = full_data["products"]
        else:
            products_map = full_data
            # Если формат был старый, конвертируем (опционально, но лучше сохранить структуру)
            # Для простоты пишем туда, где нашли
        
        # Обновляем
        products_map[key] = product_data
        
        # Сохраняем обратно
        with open(PRODUCTS_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"💾 Продукт '{name}' сохранен в базу")
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении продукта в базу: {e}")
def find_product(name: str) -> Optional[Dict]:
    """
    Ищет продукт в локальной базе данных.
    
    Args:
        name: Название продукта (нормализованное)
        
    Returns:
        Словарь с данными продукта или None
    """
    # Загружаем базу каждый раз (на случай обновления)
    db = load_products_db()
    if not db:
        return None
    
    name_lower = name.lower().strip()
    
    # Прямой поиск
    if name_lower in db:
        return db[name_lower]
    
    # Поиск по алиасам
    for product_name, product_data in db.items():
        aliases = product_data.get('aliases', [])
        # Проверяем точное совпадение с алиасами
        if name_lower in [a.lower() for a in aliases] or name_lower == product_name.lower():
            return product_data
        # Проверяем частичное совпадение с алиасами
        for alias in aliases:
            if name_lower in alias.lower() or alias.lower() in name_lower:
                return product_data
    
    # Частичное совпадение по названию продукта
    import re
    
    # Частичное совпадение по названию продукта
    for product_name, product_data in db.items():
        # Если название продукта есть в запросе (query="кефир 4%", product="кефир")
        if product_name.lower() in name_lower:
             # Проверяем, не потеряли ли мы важные цифры (проценты, жирность)
             # Находим все цифры в запросе, которых нет в найденном продукте
             query_digits = set(re.findall(r'\d+', name_lower))
             product_digits = set(re.findall(r'\d+', product_name.lower()))
             
             # Если в запросе есть цифры, которых нет в продукте - это плохой матчинг (ищем "кефир 4%", нашли "кефир")
             if not query_digits.issubset(product_digits):
                 continue
                 
             return product_data
             
        # Если запрос есть в названии продукта (query="кефир", product="кефир 3.2%") - это ок, уточнение
        if name_lower in product_name.lower():
             return product_data
    
    return None


def search_product_online(product_name: str, lang: str = 'ru') -> Optional[Dict]:
    """
    Ищет КБЖУ продукта через OpenAI API (gpt-4o-mini).
    
    Args:
        product_name: Название продукта
        lang: Язык (игнорируется в текущей реализации, промпт на русском)
        
    Returns:
        Словарь с данными продукта или None
    """
    if not product_name:
        return None
        
    api_key = get_openai_api_key()
    if not api_key:
        logger.warning("OpenAI API key not found, skipping online search")
        return None

    logger.info(f"🌐 Поиск продукта '{product_name}' через AI...")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    prompt = f"""Найди КБЖУ (калории, белки, жиры, углеводы) для продукта "{product_name}" на 100 грамм.
Ответ должен быть STRICT JSON:
{{
  "calories_per_100g": число (ккал, например 52),
  "protein_per_100g": число (г, например 0.3),
  "fats_per_100g": число (г, например 0.2),
  "carbs_per_100g": число (г, например 13.8),
  "aliases": ["вариант названия 1", "вариант названия 2"],
  "note": "краткое описание, например 'Свежее яблоко с кожурой'"
}}
Если продукт готовый (например 'пицца'), дай средние значения.
Возвращай ТОЛЬКО JSON, без markdown."""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 200
    }
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=10
        )
        # Обработка 429 (Too Many Requests)
        if response.status_code == 429:
             logger.warning("⏳ Лимит запросов (429) при поиске продукта. Ждем 2 сек...")
             time.sleep(2)
             # Повтор (один раз)
             response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=10
             )
        
        response.raise_for_status()
        result = response.json()
        
        content = result['choices'][0]['message']['content'].strip()
        # Clean markdown
        if content.startswith('```'):
            content = content.replace('```json', '').replace('```', '')
            
        data = json.loads(content)
        
        # Формируем результат
        product_data = {
            "calories_per_100g": float(data.get('calories_per_100g', 0)),
            "protein_per_100g": float(data.get('protein_per_100g', 0)),
            "fats_per_100g": float(data.get('fats_per_100g', 0)),
            "carbs_per_100g": float(data.get('carbs_per_100g', 0)),
            "aliases": data.get('aliases', []),
            "source": f"gpt-4o-mini",
            "note": data.get('note', f"AI search: {product_name}")
        }
        
        # Проверка на нули (защита от галлюцинаций)
        if product_data['calories_per_100g'] == 0 and product_data['protein_per_100g'] == 0:
            logger.warning(f"AI вернул пустые данные для {product_name}")
            return None
            
        logger.info(f"✅ AI нашел: {product_name} -> {product_data['calories_per_100g']} ккал/100г")
        
        # Сохраняем в базу (кешируем)
        save_product_to_db(product_name, product_data)
        
        return product_data
        
    except Exception as e:
        logger.error(f"Ошибка при AI поиске продукта: {e}")
        return None

