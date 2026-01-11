#!/usr/bin/env python3
"""
Модуль для распознавания изображений через Google Gemini Vision API
Использует Gemini 1.5 Flash для быстрого и точного анализа еды.
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional, List

try:
    import requests
except ImportError:
    requests = None


def get_gemini_api_key() -> Optional[str]:
    """Получает Google API ключ из различных источников"""
    # 1. Переменная окружения (GEMINI_API_KEY или GOOGLE_API_KEY)
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if api_key and api_key.strip():
        return api_key.strip()
    
    # 2. Файл в корне HealthVault
    healthvault_root = Path(__file__).parent.parent.parent
    for filename in ['.gemini_api_key', '.google_api_key']:
        key_file = healthvault_root / filename
        if key_file.exists():
            try:
                api_key = key_file.read_text().strip()
                if api_key and len(api_key) > 20:
                    return api_key
            except Exception:
                pass
    
    # 3. Файл в FamilyDocs
    family_docs = Path.home() / "FamilyDocs"
    for filename in ['.gemini_api_key', '.google_api_key']:
        key_file = family_docs / filename
        if key_file.exists():
            try:
                api_key = key_file.read_text().strip()
                if api_key and len(api_key) > 20:
                    return api_key
            except Exception:
                pass
                
    # 4. Fallback: пробуем ключ от Vision API, иногда они совпадают (но редко)
    try:
        from .api_key_loader import get_google_vision_api_key
        return get_google_vision_api_key()
    except ImportError:
        pass
        
    return None


def parse_menu_with_gemini(photo_paths: List[Path] | Path, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Распознает меню или еду через Gemini 1.5 Flash API.
    
    Args:
        photo_paths: Путь к фото или список путей
        api_key: Google API ключ
        
    Returns:
        Словарь с данными или None
    """
    if isinstance(photo_paths, (str, Path)):
        photo_paths = [Path(photo_paths)]
        
    # Фильтруем несуществующие файлы
    valid_paths = [p for p in photo_paths if p.exists()]
    
    if not valid_paths:
        return None
        
    if not api_key:
        api_key = get_gemini_api_key()
        
    if not api_key:
        print("    ⚠️  Google Gemini API ключ не найден")
        return None

    if not requests:
        print("    ❌ Библиотека requests не установлена")
        return None

    # Кодируем изображения
    image_parts = []
    for path in valid_paths:
        with open(path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",  # Gemini понимает jpg/png, мы всегда сохраняем как jpg
                    "data": base64_image
                }
            })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    prompt_text = """Analyze these food images. Identify the dish/products and estimate nutrition.
If there are multiple photos (e.g. front and back of a package, or multiple items), combine the information.
Return STRICT JSON ONLY:
{
  "dish_name": "Name of the dish or meal (in Russian)",
  "calories": total calories (number),
  "protein": total protein g (number),
  "fats": total fats g (number),
  "carbs": total carbs g (number),
  "weight_grams": estimated weight in grams (number),
  "nutrition_per_100g": {
    "calories": kcal per 100g,
    "protein": g per 100g,
    "fats": g per 100g,
    "carbs": g per 100g
  }
}
If nutritional info is visible (tables/text on packages), use it PRECISELY.
If not, ESTIMATE based on visual ingredients.
Reply ONLY with JSON."""

    # Формируем контент: текст + изображения
    content_parts = [{"text": prompt_text}] + image_parts

    payload = {
        "contents": [{
            "parts": content_parts
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }
    
    print(f"    ✨ Распознавание через Gemini 1.5 Flash...")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if response.status_code != 200:
            print(f"    ❌ Ошибка Gemini API: {response.status_code} {response.text}")
            return None
            
        result = response.json()
        
        # Извлекаем текст
        try:
            content = result['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError):
            print(f"    ❌ Неожиданный ответ от Gemini: {result}")
            return None
            
        # Clean markdown
        content = content.strip()
        if content.startswith('```'):
            content = content.split('\n', 1)[1]
            if content.endswith('```'):
                content = content[:-3]
        
        data = json.loads(content)
        
        # Валидация и корректировка
        calories = data.get('calories', 0)
        
        # Если есть per_100g и вес, но нет итогов, считаем сами
        nutr_100 = data.get('nutrition_per_100g', {})
        weight = data.get('weight_grams', 0)
        
        if weight > 0 and (not calories or calories == 0):
            multiplier = weight / 100.0
            data['calories'] = nutr_100.get('calories', 0) * multiplier
            data['protein'] = nutr_100.get('protein', 0) * multiplier
            data['fats'] = nutr_100.get('fats', 0) * multiplier
            data['carbs'] = nutr_100.get('carbs', 0) * multiplier
            
        print(f"    ✅ Gemini распознал: {data.get('dish_name')} ({data.get('calories')} ккал)")
        
        return {
            'dish_name': data.get('dish_name', 'Блюдо'),
            'calories': float(data.get('calories', 0)),
            'protein': float(data.get('protein', 0)),
            'fats': float(data.get('fats', 0)),
            'carbs': float(data.get('carbs', 0)),
            'weight': float(weight) if weight else None,
            'nutrition_per_100g': data.get('nutrition_per_100g'),
            'source': 'gemini_vision'
        }
        
    except Exception as e:
        print(f"    ❌ Ошибка при запросе к Gemini: {e}")
        return None
