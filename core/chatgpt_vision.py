#!/usr/bin/env python3
"""
Модуль для распознавания изображений через ChatGPT Vision API
Использует GPT-4 Vision для умного извлечения данных из фото меню, весов и т.д.
"""

import base64
import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional, List
import time

# Add project root to path for config import
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings

try:
    from infrastructure.cache.image_cache import get_image_cache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    get_image_cache = None


def get_openai_api_key() -> Optional[str]:
    """Получает OpenAI API ключ из конфигурации"""
    settings = get_settings()
    return settings.openai_api_key


def encode_image(image_path: Path) -> str:
    """Кодирует изображение в base64 для отправки в API"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def parse_menu_with_chatgpt(photo_path: Path, api_key: Optional[str] = None, description: Optional[str] = None) -> Optional[Dict]:
    """
    Распознает меню кафе с КБЖУ через ChatGPT Vision API.
    
    Args:
        photo_path: Путь к фото меню
        api_key: OpenAI API ключ (опционально)
        description: Описание блюда от пользователя (опционально)
        
    Returns:
        Словарь с данными блюда или None:
        {
            'dish_name': 'Quinoa Tuna Bowl',
            'calories': 597.0,
            'protein': 25.8,
            'fats': 24.2,
            'carbs': 69.2,
            'weight': None
        }
    """
    if not photo_path.exists():
        print(f"    ❌ Файл не существует: {photo_path}")
        return None
    
    # Проверяем кэш
    if CACHE_AVAILABLE and get_settings().cache_enabled:
        cache = get_image_cache()
        cached_result = cache.get(photo_path)
        if cached_result:
            print(f"    ✅ Используем кэш для изображения {photo_path.name}")
            print(f"       💰 Экономия: ~$0.01 (Vision API вызов пропущен)")
            return cached_result
    
    # Получаем API ключ
    if not api_key:
        api_key = get_openai_api_key()
    
    if not api_key:
        print("    ⚠️  OpenAI API ключ не найден")
        return None
    
    # Debug log
    masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "INVALID_LEN"
    print(f"    🔑 ChatGPT Vision using key: {masked_key}")
    
    try:
        import requests
    except ImportError:
        print("    ❌ Библиотека requests не установлена")
        return None
    
    # Кодируем изображение
    base64_image = encode_image(photo_path)
    
    # Формируем запрос к ChatGPT Vision API
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    user_context = ""
    meal_type_hint = ""
    if description:
        # Определяем hint для типа приема пищи из description
        description_lower = description.lower()
        if any(word in description_lower for word in ['завтрак', 'breakfast']):
            meal_type_hint = "Время приема: завтрак."
        elif any(word in description_lower for word in ['обед', 'lunch']):
            meal_type_hint = "Время приема: обед."
        elif any(word in description_lower for word in ['ужин', 'dinner']):
            meal_type_hint = "Время приема: ужин."
        elif any(word in description_lower for word in ['перекус', 'snack']):
            meal_type_hint = "Время приема: перекус."
        
        user_context = f"КОНТЕКСТ ОТ ПОЛЬЗОВАТЕЛЯ: \"{description}\". {meal_type_hint} Используй это для уточнения ингредиентов и времени приема пищи."
    
    prompt = f"""Проанализируй это изображение еды, меню или добавок.
    {user_context}
    
ЦЕЛЬ: Оценить нутриенты для дневника питания.

ВАЖНО О НАЗВАНИИ БЛЮДА:
- Если на изображении есть МЕНЮ с названием блюда - используй ТОЛЬКО название с меню
- Если пользователь написал "завтрак"/"обед"/"ужин"/"перекус" - это время приема пищи, НЕ название блюда
- Название блюда должно описывать ЧТО изображено (например: "Боул с индейкой, эдамаме и фунчозой")
- description от пользователя используй ТОЛЬКО для уточнения ингредиентов, НЕ для замены названия блюда

ПРИОРИТЕТ ИНГРЕДИЕНТОВ:
Если пользователь упомянул конкретные ингредиенты (НЕ "завтрак/обед/ужин"), найди и верни ВСЕ эти компоненты.
НЕ ИГНОРИРУЙ ингредиенты из описания!

СЦЕНАРИЙ 1: ВИТАМИНЫ / ТАБЛЕТКИ / БАДЫ
Если на фото таблетки, капсулы, блистеры или банки с витаминами:
- Формат JSON:
{{
  "is_supplement": true,
  "dish_name": "список распознанных добавок",
  "calories": 0,
  "protein": 0,
  "fats": 0,
  "carbs": 0,
  "weight_grams": 0
}}

СЦЕНАРИЙ 2: ЕДА / ПРОДУКТЫ / МЕНЮ
ТВОЯ ГЛАВНАЯ ЦЕЛЬ - РАЗБИТЬ НА КОМПОНЕНТЫ.

Если на фото НЕСКОЛЬКО РАЗНЫХ объектов (например: банка протеина + банан + бутылка воды):
- ТЫ ОБЯЗАН вернуть список "components".
- КАЖДЫЙ объект должен быть отдельным компонентом.
- Не суммируй КБЖУ в одну кучу, если компоненты разные.
- ДЛЯ УПАКОВОК: Считай КБЖУ для того веса, который указал пользователь (или стандартной порции), используя данные с этикетки (на 100г).

Если это ГОТОВОЕ БЛЮДО (тарелка с едой) или СМЕШАННЫЙ ПРИЕМ ПИЩИ:
- Раздели на компоненты (мясо, гарнир, салат и т.д.).
- ОЦЕНИ вес каждого компонента.
- РАССЧИТАЙ КБЖУ для каждого компонента.

Формат JSON для еды:
{{
  "dish_name": "название блюда С МЕНЮ или описание того, что на фото (НЕ 'завтрак'/'обед'/'ужин')",
  "calories": число (сумма калорий компонентов),
  "protein": число (сумма),
  "fats": число (сумма),
  "carbs": число (сумма),
  "weight_grams": число (общий вес),
  "nutrition_per_100g": {{
    "calories": число,
    "protein": число,
    "fats": число,
    "carbs": число
  }},
  "components": [
    {{
      "name": "название ингредиента (например 'Индейка')",
      "weight": число (г),
      "calories": число,
      "protein": число,
      "fats": число,
      "carbs": число
    }}
  ]
}}

Возвращай ТОЛЬКО JSON."""

    payload = {
        "model": "gpt-4o",  # или "gpt-4-vision-preview" для старых версий
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.1  # Низкая температура для более точных результатов
    }
    
    print(f"    🤖 Распознавание меню через ChatGPT Vision...")
    
    # Retry при 429 ошибке
    max_retries = 2
    retry_delay = 5  # секунд
    result = None
    
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            # Если 429 - ждем и пробуем снова
            if response.status_code == 429:
                if attempt < max_retries:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"    ⏳ Лимит запросов (429). Жду {wait_time} сек...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ⚠️  Лимит запросов (429) после {max_retries} попыток")
                    return None
            
            response.raise_for_status()
            result = response.json()
            break  # Успешно, выходим из цикла
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "429" in error_msg or "Too Many Requests" in error_msg:
                if attempt < max_retries:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"    ⏳ Лимит запросов (429). Жду {wait_time} сек...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ⚠️  ChatGPT API: лимит запросов (429). Подождите немного.")
            elif "401" in error_msg or "Unauthorized" in error_msg:
                print(f"    ❌ ChatGPT API: неверный API ключ (401)")
            else:
                if hasattr(e, 'response') and e.response is not None:
                     print(f"    ❌ Детали ошибки API: {e.response.text}")
                print(f"    ❌ Ошибка запроса к ChatGPT API: {e}")
                print(f"    ❌ Ошибка запроса к ChatGPT API: {e}")
            return None
        except Exception as e:
            print(f"    ❌ Ошибка при распознавании через ChatGPT: {e}")
            return None
    
    if not result:
        return None
    
    # Извлекаем ответ
    if 'choices' in result and len(result['choices']) > 0:
        content = result['choices'][0]['message']['content']
        
        # Парсим JSON из ответа
        # ChatGPT может вернуть JSON в markdown блоках или просто текст
        content = content.strip()
        
        # Убираем markdown блоки если есть
        if '```json' in content:
            # Ищем блок кода
            match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1)
        elif '```' in content:
            match = re.search(r'```\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1)
        
        # Парсим JSON
        try:
            # Очищаем от возможных лишних символов
            content = content.strip()
            # Если начинается с "Here is the JSON" или подобного, ищем первую { и последнюю }
            if not content.startswith('{'):
                start = content.find('{')
                end = content.rfind('}')
                if start != -1 and end != -1:
                    content = content[start:end+1]
            
            data = json.loads(content)
            
            # Если есть nutrition_per_100g и weight_grams, пересчитываем КБЖУ для всей порции
            nutrition_per_100g = data.get('nutrition_per_100g', {})
            weight_grams = data.get('weight_grams')
            
            if nutrition_per_100g and weight_grams and weight_grams > 0:
                # Пересчитываем КБЖУ для всей порции
                multiplier = weight_grams / 100.0
                
                # Если основные поля не заполнены или равны 0, пересчитываем из nutrition_per_100g
                if not data.get('calories') or data.get('calories', 0) == 0:
                    data['calories'] = nutrition_per_100g.get('calories', 0) * multiplier
                if not data.get('protein') or data.get('protein', 0) == 0:
                    data['protein'] = nutrition_per_100g.get('protein', 0) * multiplier
                if not data.get('fats') or data.get('fats', 0) == 0:
                    data['fats'] = nutrition_per_100g.get('fats', 0) * multiplier
                if not data.get('carbs') or data.get('carbs', 0) == 0:
                    data['carbs'] = nutrition_per_100g.get('carbs', 0) * multiplier
                
                print(f"    ✅ Пересчитано КБЖУ для порции {weight_grams}г:")
                print(f"       Калории: {nutrition_per_100g.get('calories', 0)} ккал/100г × {multiplier:.2f} = {data.get('calories', 0):.1f} ккал")
                print(f"       Белки: {nutrition_per_100g.get('protein', 0)}г/100г × {multiplier:.2f} = {data.get('protein', 0):.1f}г")
                print(f"       Жиры: {nutrition_per_100g.get('fats', 0)}г/100г × {multiplier:.2f} = {data.get('fats', 0):.1f}г")
                print(f"       Углеводы: {nutrition_per_100g.get('carbs', 0)}г/100г × {multiplier:.2f} = {data.get('carbs', 0):.1f}г")
            
            # Проверяем наличие необходимых полей
            calories = data.get('calories')
            if calories is not None and calories > 0:
                # Безопасно получаем значения с дефолтами
                protein = data.get('protein') or 0
                fats = data.get('fats') or 0
                carbs = data.get('carbs') or 0
                
                print(f"    ✅ ChatGPT распознал: {data.get('dish_name', 'Блюдо')}")
                print(f"       КБЖУ: {calories} ккал, "
                      f"Б: {protein}г, "
                      f"Ж: {fats}г, "
                      f"У: {carbs}г")
                
                # Сохраняем исходные значения на 100г для последующего пересчета
                nutrition_per_100g_result = nutrition_per_100g if nutrition_per_100g else {
                    'calories': calories / ((weight_grams / 100.0) if weight_grams and weight_grams > 0 else 1.0),
                    'protein': protein / ((weight_grams / 100.0) if weight_grams and weight_grams > 0 else 1.0),
                    'fats': fats / ((weight_grams / 100.0) if weight_grams and weight_grams > 0 else 1.0),
                    'carbs': carbs / ((weight_grams / 100.0) if weight_grams and weight_grams > 0 else 1.0),
                }
                
                # Если есть nutrition_per_100g из ответа ChatGPT, используем его
                if nutrition_per_100g:
                    nutrition_per_100g_result = {
                        'calories': nutrition_per_100g.get('calories', calories),
                        'protein': nutrition_per_100g.get('protein', protein),
                        'fats': nutrition_per_100g.get('fats', fats),
                        'carbs': nutrition_per_100g.get('carbs', carbs),
                    }
                
                # Валидация значений - проверяем разумность
                # Жиры и углеводы на 100г обычно не превышают 50-60г для большинства продуктов
                # Если значения слишком высокие (>80г), вероятно ошибка распознавания
                validated_fats = float(fats)
                validated_carbs = float(carbs)
                
                # Если nutrition_per_100g есть, валидируем его
                if nutrition_per_100g_result:
                    per_100g_fats = nutrition_per_100g_result.get('fats', 0)
                    per_100g_carbs = nutrition_per_100g_result.get('carbs', 0)
                    
                    # Если значения на 100г выглядят неразумно (>80г), возможно это ошибка
                    # Проверяем, не перепутаны ли значения (например, 100г вместо 24г)
                    if per_100g_fats > 80:
                        print(f"    ⚠️  Предупреждение: жиры на 100г = {per_100g_fats}г выглядят неразумно")
                        # Пробуем найти правильное значение в исходных данных
                        if nutrition_per_100g and nutrition_per_100g.get('fats', 0) < 80:
                            per_100g_fats = nutrition_per_100g.get('fats', 0)
                            print(f"    ✅ Исправлено: используем {per_100g_fats}г жиров на 100г")
                    
                    if per_100g_carbs > 80:
                        print(f"    ⚠️  Предупреждение: углеводы на 100г = {per_100g_carbs}г выглядят неразумно")
                        if nutrition_per_100g and nutrition_per_100g.get('carbs', 0) < 80:
                            per_100g_carbs = nutrition_per_100g.get('carbs', 0)
                            print(f"    ✅ Исправлено: используем {per_100g_carbs}г углеводов на 100г")
                    
                    nutrition_per_100g_result['fats'] = per_100g_fats
                    nutrition_per_100g_result['carbs'] = per_100g_carbs
                
                
                dish_name = data.get('dish_name')
                if not dish_name or str(dish_name).lower() == 'none':
                    dish_name = 'Блюдо из меню'
                
                result = {
                    'dish_name': dish_name,
                    'calories': float(calories),
                    'protein': float(protein),
                    'fats': validated_fats,
                    'carbs': validated_carbs,
                    'weight': data.get('weight_grams') or data.get('weight'),
                    'nutrition_per_100g': nutrition_per_100g_result,  # Сохраняем исходные значения на 100г
                    'components': data.get('components', []), # Сохраняем компоненты
                    'source': 'chatgpt_vision',
                }
                
                # Сохраняем в кэш
                if CACHE_AVAILABLE and get_settings().cache_enabled:
                    cache = get_image_cache()
                    cache.set(photo_path, result)
                    print(f"    💾 Результат сохранен в кэш")
                
                return result
            else:
                print(f"    ⚠️  ChatGPT не нашел КБЖУ в изображении")
                return None
                
        except json.JSONDecodeError as e:
            print(f"    ❌ Ошибка парсинга JSON от ChatGPT: {e}")
            print(f"    Ответ: {content[:200]}")
            return None
    else:
        print(f"    ❌ Неожиданный формат ответа от ChatGPT")
        return None


def parse_text_description_with_chatgpt(description: str, api_key: Optional[str] = None) -> Optional[List[Dict]]:
    """
    Распознает продукты из текстового описания еды через ChatGPT API.
    
    Args:
        description: Текстовое описание блюда (например, "обед: яичница из 2-х яиц, маленькой луковички, 6 томатов черри: маленького кусочка сливочного масла и 30 грамм сыра")
        api_key: OpenAI API ключ (опционально)
        
    Returns:
        Список продуктов с весами или None:
        [
            {'name': 'яйцо', 'weight': 100.0, 'source': 'chatgpt'},
            {'name': 'лук', 'weight': 50.0, 'source': 'chatgpt'},
            {'name': 'томат черри', 'weight': 120.0, 'source': 'chatgpt'},
            {'name': 'сливочное масло', 'weight': 15.0, 'source': 'chatgpt'},
            {'name': 'сыр', 'weight': 30.0, 'source': 'chatgpt'}
        ]
    """
    if not description or len(description.strip()) < 3:
        return None
    
    # Получаем API ключ
    if not api_key:
        api_key = get_openai_api_key()
    
    if not api_key:
        print("    ⚠️  OpenAI API ключ не найден для обработки текста")
        return None
    
    try:
        import requests
    except ImportError:
        print("    ❌ Библиотека requests не установлена")
        return None
    
    # Формируем промпт
    prompt = """Проанализируй это описание еды и извлеки список продуктов с их весами в формате JSON.

Описание: {description}

КРИТИЧЕСКИ ВАЖНО - РАЗЛИЧЕНИЕ ГОТОВЫХ БЛЮД И СУХИХ ПРОДУКТОВ:

Rule A (по умолчанию): Если пользователь пишет "каша", "гречка готовая", "рис", "макароны", "пюре", "гарнир" БЕЗ слова "сухой/крупа/в сухом виде", то считать как ГОТОВОЕ блюдо.
- "пшённая каша" = ГОТОВАЯ каша (120 ккал/100г), НЕ сухое пшено (348 ккал/100г)
- "гречневая каша" = ГОТОВАЯ гречка (110 ккал/100г), НЕ сухая крупа (343 ккал/100г)
- "рис" или "рис варёный" = ГОТОВЫЙ рис (130 ккал/100г), НЕ сухой рис (365 ккал/100г)
- "макароны" или "паста" = ГОТОВЫЕ макароны (150 ккал/100г), НЕ сухие (371 ккал/100г)

Rule B: Если пользователь явно пишет "сухая крупа", "пшено (крупа)", "взвесил сухое", "до варки" - считать как сухой продукт.

Rule C: Если есть признаки неоднозначности (например: "200г пшена" без слова каша/готовое), верни basis: "ambiguous" для этого продукта.

Извлеки ВСЕ продукты из описания и укажи их веса в граммах. Если вес не указан явно, оцени его:
- "2 яйца" или "2-х яиц" = 100г (50г на яйцо среднего размера)
- "маленькая луковичка" = 50г, "средняя" = 100г, "большая" = 150г
- "6 томатов черри" = 120г (20г на томат черри)
- "маленький кусочек масла" = 15г, "кусок" = 30г
- "30 грамм сыра" = 30г (точно указано)
- "чайная ложка" = 5г, "столовая ложка" = 15г
- "порция каши" = 150-200г готовой каши (НЕ сухой крупы!)

ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА:
- Игнорируй названия приёмов пищи (обед, завтрак, ужин, перекус) - они НЕ являются продуктами
- Если описание начинается с "обед:", "завтрак:" и т.д. - это НЕ продукт, пропусти его полностью
- Возвращай ТОЛЬКО реальные продукты питания, которые были съедены
- Вес должен быть в граммах (только число, без единиц)
- Названия продуктов должны быть нормализованными, НО сохранять важные детали:
  * "кефир 4%" (НЕ просто "кефир", если указана жирность)
  * "творог 5%" (НЕ просто "творог")
  * "молоко 3.2%"
  * "яйцо" (не "яиц", не "яйца")
  * "сыр" (не "сыра")
  * "лук" (не "луковички", не "луковицы")
  * "томат черри" или "томат" (не "томатов", не "помидоров")
  * "сливочное масло" (не "масла")
  * "пшённая каша" (если готовое) или "пшено сухое" (если сухое)

Формат ответа (JSON):
{{
  "products": [
    {{"name": "пшённая каша", "weight": 200, "basis": "cooked"}},
    {{"name": "яйцо", "weight": 100, "basis": "raw"}},
    {{"name": "томат черри", "weight": 60, "basis": "raw"}},
    {{"name": "огурец", "weight": 50, "basis": "raw"}}
  ]
}}

basis может быть: "cooked" (готовое), "raw" (сырое), "dry" (сухое), "packaged" (упаковка), "ambiguous" (неоднозначно).

Возвращай ТОЛЬКО валидный JSON, без дополнительного текста, без markdown блоков.""".format(description=description)
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": "gpt-4o",  # Используем gpt-4o для текста тоже
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.1  # Низкая температура для более точных результатов
    }
    
    print(f"    🤖 Обработка описания через ChatGPT...")
    
    # Retry при 429 ошибке
    max_retries = 2
    retry_delay = 5  # секунд
    result = None
    
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            # Если 429 - ждем и пробуем снова
            if response.status_code == 429:
                if attempt < max_retries:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"    ⏳ Лимит запросов (429). Жду {wait_time} сек...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ⚠️  Лимит запросов (429) после {max_retries} попыток")
                    return None
            
            response.raise_for_status()
            result = response.json()
            break  # Успешно, выходим из цикла
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "429" in error_msg or "Too Many Requests" in error_msg:
                if attempt < max_retries:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"    ⏳ Лимит запросов (429). Жду {wait_time} сек...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    ⚠️  ChatGPT API: лимит запросов (429). Подождите немного.")
            elif "401" in error_msg or "Unauthorized" in error_msg:
                print(f"    ❌ ChatGPT API: неверный API ключ (401)")
            else:
                print(f"    ❌ Ошибка запроса к ChatGPT API: {e}")
            return None
        except Exception as e:
            print(f"    ❌ Ошибка при обработке через ChatGPT: {e}")
            return None
    
    if not result:
        return None
    
    # Извлекаем ответ
    if 'choices' in result and len(result['choices']) > 0:
        content = result['choices'][0]['message']['content']
        
        # Парсим JSON из ответа
        content = content.strip()
        
        # Убираем markdown блоки если есть
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content
            # Убираем "json" из первой строки если есть
            if content.startswith('json'):
                content = '\n'.join(content.split('\n')[1:])
        
        # Парсим JSON
        try:
            data = json.loads(content)
            
            # Проверяем наличие продуктов
            products_list = data.get('products', [])
            if not products_list:
                print(f"    ⚠️  ChatGPT не нашел продукты в описании")
                return None
            
            # Конвертируем в нужный формат
            result_products = []
            for product in products_list:
                name = product.get('name', '').strip()
                weight = product.get('weight', 0)
                basis = product.get('basis', 'raw')  # По умолчанию raw
                
                # Пропускаем, если это название приёма пищи
                meal_names = ['обед', 'завтрак', 'ужин', 'перекус', 'бранч', 'полдник']
                if name.lower() in meal_names:
                    print(f"    ⚠️  Пропущен '{name}' (название приёма пищи)")
                    continue
                
                if name and weight > 0:
                    result_products.append({
                        'name': name,
                        'weight': float(weight),
                        'basis': basis,  # Сохраняем basis из ChatGPT
                        'source': 'chatgpt'
                    })
            
            # Дедупликация: убираем полные дубликаты (имя + вес)
            unique_products = []
            seen_combinations = set()
            
            for p in result_products:
                # Нормализуем имя для сравнения
                norm_name = p['name'].lower().strip()
                weight_key = round(p['weight'], 1)
                
                key = (norm_name, weight_key)
                
                if key not in seen_combinations:
                    seen_combinations.add(key)
                    unique_products.append(p)
                else:
                    print(f"    ⚠️  Убран дубликат из ответа ChatGPT: {p['name']} ({p['weight']}г)")
            
            result_products = unique_products

            
            if result_products:
                print(f"    ✅ ChatGPT распознал {len(result_products)} продуктов:")
                for p in result_products:
                    print(f"       • {p['name']}: {p['weight']}г")
                return result_products
            else:
                print(f"    ⚠️  ChatGPT не нашел валидные продукты")
                return None
                
        except json.JSONDecodeError as e:
            print(f"    ❌ Ошибка парсинга JSON от ChatGPT: {e}")
            print(f"    Ответ: {content[:200]}")
            return None
    else:
        print(f"    ❌ Неожиданный формат ответа от ChatGPT")
        return None
