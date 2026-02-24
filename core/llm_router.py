#!/usr/bin/env python3
"""
LLM Router: Central intelligence for the bot.
Classifies messages (Text/Photo) and extracts structured data using GPT-4o.
"""

import json
import base64
import sys
import requests
import time
from pathlib import Path
from typing import List, Optional, Dict, Union

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings
from core.llm_models import parse_llm_response
import logging

logger = logging.getLogger(__name__)

def get_openai_api_key() -> Optional[str]:
    """Получает OpenAI API ключ из .env (OPENAI_API_KEY)."""
    return get_settings().openai_api_key

def encode_image(image_path: Path) -> str:
    """Encodes image to base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

SYSTEM_PROMPT = """You are the AI brain of a Health Logger Bot.
Your goal is to CLASSIFY the user's message (Text and/or Photos) and EXTRACT structured data.

CLASSIFICATION CATEGORIES:
1. "food": Meal descriptions, photos of food/menus, cooking ingredients (EXCLUDING clear supplements like Psyllium/Vitamins unless used as baking ingredient).
2. "weight": Photos of weight scales, text like "80.5 kg", body composition screens.
3. "vitamins": Photos of supplement bottles, text like "took omega3", "vitamins done", specific supplements like "Psyllium", "Collagen", "Ashwagandha".
4. "medical": Lab results, doctor notes (if clearly medical).
5. "other": General chat, questions not related to logging, or unclear inputs.

OUTPUT FORMAT:
Return ONLY valid JSON. Structure depends on category.

SCENARIO 1: FOOD
Extract ALL ingredients. If it's a dish, break it down if possible.
IMPORTANT: Return "name" in RUSSIAN language (e.g. "Морковь", not "Carrot").
{
  "type": "food",
  "data": {
    "dish_name": "Description of the meal",
    "meal_type": "breakfast/lunch/dinner/snack" (guess by context/time),
    "items": [
      {
        "name": "Ingredient name",
        "weight": number (grams) OR null if unknown,
        "quantity": "count/volume string" (e.g. "1 cup", "2 slices"),
        "calories": number (approx, if standard),
        "protein": number,
        "fats": number,
        "carbs": number
      }
    ],
    "total_nutrition": {
      "calories": number,
      "protein": number,
      "fats": number,
      "carbs": number
    }
  }
}

SCENARIO 1.1: RECIPE CARDS / LABELS (CRITICAL)
- If image has EXPLICIT TOTALS (e.g. "668 kcal", "B: 47"):
  1. Extract EXACT values into `total_nutrition`.
  2. TRUST these totals 100%.
  3. List ingredients in `items` normally.
CRITICAL FOR FOOD:
- Use USER provided weights if present (e.g. "100g carrot" -> weight: 100).
- If macros are provided in text (e.g. "Fat: 0.4g"), USE THEM exact. DO NOT interpret "0.4" as a percentage multiplier!
- If text says "raw carrot 100g", item name is "raw carrot", weight is 100.
- Do NOT leave weight and calories as null/0 for well-known dishes. ALWAYS estimate standard portion weight and macros.
- If user lists dishes without weight (e.g. "lentil soup, salad, kebab"), use standard portion sizes from the database below.
- NEVER return 0 calories for real food items. Estimate using your knowledge of typical nutritional values.

STANDARD PORTIONS DATABASE (use when exact weight not provided):

МАСЛА и ЖИРЫ:
- Подсолнечное/оливковое масло: 1 ч.л. = 5г, 1 ст.л. = 15г
- Сливочное масло: 1 ч.л. = 5г, 1 ст.л. = 12г
- Авокадо: 1/2 среднего = 100г, целый = 200г

ОВОЩИ и ЗЕЛЕНЬ:
- Томаты черри: 1 шт = 15-20г, 5 шт = 85г
- Томат средний: 1 шт = 120г
- Огурец средний: 1 шт = 100г
- Оливки/маслины: 1 шт = 5г, 6 шт = 30г, 10 шт = 50г
- Редис: 1 шт = 15г
- Лук репчатый средний: 1 шт = 75г
- Морковь средняя: 1 шт = 70-80г
- Чеснок: 1 зубчик = 3-5г
- Листья салата: 1 порция = 30-50г
- Брокколи: 1 соцветие = 30г
- Сельдерей стебель: 1 шт = 40г

ХЛЕБ и ВЫПЕЧКА:
- Зерновой хлеб: 1 тонкий ломтик = 25-30г, 1 толстый = 40-50г
- Белый хлеб: 1 ломтик = 30г
- Багет: 1 кусок = 40-50г
- Лаваш тонкий: 1 лист = 50-70г
- Тост: 1 шт = 25-30г
- Булочка для бургера: 1 шт = 50-60г

ЯЙЦА:
- Куриное яйцо: 1 маленькое (S) = 45г, 1 среднее (M) = 55г, 1 крупное (L) = 65г
- Яйцо без скорлупы: вычесть ~10% от веса
- 3 яйца средних = 165г (целиком со скорлупой) или 150г (без)

МОЛОЧНЫЕ ПРОДУКТЫ:
- Сыр твердый: 1 ломтик = 20-30г
- Моцарелла: 1 шарик = 125г
- Творог: 1 пачка = 200-250g
- Йогурт: 1 стаканчик = 125-150g
- Молоко: 1 стакан = 200мл

КРУПЫ и ПАСТА (сухой вес):
- Рис: 1 порция = 60-80г (сухой)
- Гречка: 1 порция = 60-80г (сухой)
- Овсянка: 1 порция = 50г (сухой)
- Паста: 1 порция = 80-100г (сухой)

ФРУКТЫ:
- Яблоко среднее: 1 шт = 150-180г
- Банан средний: 1 шт без кожуры = 120г
- Апельсин: 1 шт = 150г
- Киви: 1 шт = 70-80г
- Клубника: 1 шт = 12-15г

МЯСО и РЫБА (готовый продукт):
- Куриная грудка: 1 средняя = 150-200г
- Стейк: 1 порция = 150-200г
- Филе рыбы: 1 порция = 120-150г
- Тунец консервированный: 1 банка = 150г

ОРЕХИ и СЕМЕЧКИ:
- Миндаль: 10 шт = 10-12г
- Грецкий орех: 5 половинок = 15г
- Кешью: 10 шт = 15г
- Семечки подсолнуха: 1 ст.л. = 15г

ГОТОВЫЕ БЛЮДА (1 стандартная порция в ресторане/дома):
- Борщ/щи: 300г, ~120 ккал (Б:5 Ж:4 У:15)
- Куриный/овощной/грибной суп: 300г, ~100-150 ккал
- Суп чечевичный/гороховый: 300г, ~180 ккал (Б:12 Ж:4 У:25)
- Солянка: 300г, ~130 ккал (Б:8 Ж:7 У:8)
- Овощной салат (греческий, турецкий, шопский): 200г, ~120 ккал (Б:3 Ж:8 У:10)
- Оливье/Цезарь: 200г, ~280 ккал (Б:10 Ж:18 У:18)
- Люля-кебаб: 1 шт = 100г, ~200 ккал (Б:12 Ж:16 У:2)
- Шашлык: 200г, ~350 ккал (Б:25 Ж:27 У:0)
- Котлеты (мясные): 1 шт = 80г, ~200 ккал (Б:12 Ж:15 У:7)
- Пельмени (порция): 250г, ~500 ккал (Б:20 Ж:20 У:55)
- Плов: 300г, ~450 ккал (Б:15 Ж:18 У:55)
- Каша на воде (порция): 250г, ~200 ккал
- Паста/макароны (порция): 250г готовой, ~350 ккал
- Пицца: 1 кусок = 100г, ~250 ккал
- Блины с начинкой: 1 шт = 80г, ~200 ккал
- Рагу овощное: 250г, ~120 ккал
- Гуляш: 250г, ~280 ккал (Б:20 Ж:16 У:12)

CRITICAL RULES FOR ACCURACY:
1. ALWAYS convert spoons to grams: "1 ч.л. масла" -> weight: 5
2. ALWAYS convert pieces to grams: "6 оливок" -> weight: 30
3. For eggs: Use 55g per egg if size not specified
4. If user says "чайная ложка" or "столовая ложка" - ALWAYS provide weight in grams
5. NEVER leave weight as null if portion type is known (spoons, pieces, slices)
6. For dishes without explicit weight (soup, salad, kebab etc) - ALWAYS use standard portion from database above
7. NEVER return calories: 0 for a real food item. Estimate based on your nutritional knowledge

SCENARIO 2: WEIGHT
Extract weight and body composition.
{
  "type": "weight",
  "data": {
    "weight": number (kg),
    "body_fat": number (percent) or null,
    "muscle_mass": number (kg) or null,
    "visceral_fat": number or null,
    "water_percent": number or null,
    "date": "YYYY-MM-DD" (if visible/stated, otherwise null)
  }
}

SCENARIO 3: VITAMINS
IMPORTANT: Return "items" in RUSSIAN language (e.g. "Витамин С", "Магний").
{
  "type": "vitamins",
  "data": {
    "items": ["Витамин С", "Омега-3"],
    "action": "logged"
  }
}

SCENARIO 4: OTHER
{
  "type": "other",
  "data": {
    "reply": "Brief helpful reply or clarity question"
  }
}
"""

def analyze_message(text: str = None, image_paths: List[Union[str, Path]] = None) -> Optional[Dict]:
    """
    Analyzes message content using GPT-4o.
    Returns structured JSON or None on failure.
    """
    api_key = get_openai_api_key()
    if not api_key:
        print("❌ OpenAI API Key missing")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # Build content list
    content = []
    
    # Add text if present
    if text:
        content.append({"type": "text", "text": f"USER MESSAGE: {text}"})
    
    # Add images if present
    if image_paths:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                b64 = encode_image(path_obj)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })

    if not content:
        return None

    # Construct payload
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ],
        "max_tokens": 2000,
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    # Retry logic
    for attempt in range(3):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
                
            response.raise_for_status()
            result = response.json()
            
            content_str = result['choices'][0]['message']['content']
            if content_str is None:
                print(f"❌ OpenAI returned None content. Finish reason: {result['choices'][0].get('finish_reason')}")
                # Fallback to empty json to trigger retry or return None
                raise ValueError("OpenAI returned None content")
                
            parsed_json = json.loads(content_str)
            return parse_llm_response(parsed_json)
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403 or e.response.status_code == 401:
                print(f"❌ OpenAI API {e.response.status_code} (Auth). Falling back to Gemini...")
                return analyze_message_gemini(text, image_paths)
            print(f"Error in LLM Router (Attempt {attempt+1}): {e}")
            time.sleep(1)
        except requests.exceptions.ConnectionError as e:
            print(f"❌ OpenAI Connection Error. Falling back to Gemini...")
            return analyze_message_gemini(text, image_paths)
        except Exception as e:
            print(f"Error in LLM Router (Attempt {attempt+1}): {e}")
            time.sleep(1)

    logger.warning(
        "LLM Router: OpenAI не ответил после всех попыток. "
        "Если бот пишет «OpenAI не отвечает» — возможно, закончились токены по ключу: доложи баланс в OpenAI."
    )
    return None

def analyze_message_gemini(text: str = None, image_paths: List[Union[str, Path]] = None) -> Optional[Dict]:
    """
    Analyzes message content using Google Gemini 1.5 Flash (Fallback for OpenAI).
    """
    settings = get_settings()
    api_key = settings.gemini_api_key or settings.google_api_key
    
    if not api_key:
        print("    ⚠️  Gemini API Key missing")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    # Build parts
    parts = [{"text": SYSTEM_PROMPT}]
    if text:
        parts.append({"text": f"USER MESSAGE: {text}"})
    
    if image_paths:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                with open(path_obj, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64
                        }
                    })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }
    
    print(f"    ✨ Attempting recognition through Gemini 1.5 Flash...")
    
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 429:
                wait = (attempt + 1) * 3
                logger.warning(f"Gemini 429 (rate limit), retry {attempt+1}/3 через {wait} сек")
                time.sleep(wait)
                continue
            response.raise_for_status()
            result = response.json()
            
            content = result['candidates'][0]['content']['parts'][0]['text']
            # Clean markdown if present
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[1]
                if content.endswith('```'):
                    content = content[:-3]
            
            return parse_llm_response(json.loads(content))
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and attempt < 2:
                wait = (attempt + 1) * 3
                logger.warning(f"Gemini 429 (rate limit), retry {attempt+1}/3 через {wait} сек")
                time.sleep(wait)
                continue
            logger.warning(f"Gemini Fallback failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Gemini Fallback failed: {e}")
            return None
    return None

if __name__ == "__main__":
    # Simple test
    test_text = "ужин: сырая морковь 100 г, варенная свекла 150 г, тунец 100 г"
    print(f"Testing with: {test_text}")
    print(json.dumps(analyze_message(text=test_text), indent=2, ensure_ascii=False))
