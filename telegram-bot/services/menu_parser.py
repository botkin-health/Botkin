#!/usr/bin/env python3
"""
Модуль для распознавания меню кафе с КБЖУ из фото
"""

import re
from pathlib import Path
from typing import Dict, Optional
import sys

# Добавляем путь к скриптам для импорта OCR
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
try:
    from google_vision_ocr import ocr_with_google_vision
except ImportError:
    ocr_with_google_vision = None

from .api_key_loader import get_google_vision_api_key

# Пробуем импортировать ChatGPT Vision
try:
    from .chatgpt_vision import parse_menu_with_chatgpt, get_openai_api_key
    CHATGPT_AVAILABLE = True
except ImportError:
    CHATGPT_AVAILABLE = False
    CHATGPT_AVAILABLE = False
    parse_menu_with_chatgpt = None

# Пробуем импортировать Gemini Vision
try:
    from .gemini_vision import parse_menu_with_gemini
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    parse_menu_with_gemini = None


def extract_nutrition_from_text(text: str) -> Optional[Dict[str, float]]:
    """
    Извлекает КБЖУ из текста OCR меню.
    Ищет паттерны типа:
    - "597 kcal" или "597 ккал"
    - "25,8 g protein" или "25.8 г белка"
    - "24,2 g fat" или "24.2 г жиров"
    - "69,2 g carbs" или "69.2 г углеводов"
    
    Также поддерживает формат, где числа и метки на разных строках:
    "25,8 g
     protein"
    
    Args:
        text: Текст, распознанный через OCR
        
    Returns:
        Словарь с КБЖУ или None, если не найдено:
        {'calories': 597.0, 'protein': 25.8, 'fats': 24.2, 'carbs': 69.2}
    """
    if not text:
        return None
    
    nutrition = {}
    
    # Паттерны для калорий
    # "597 kcal", "597 ккал", "597 kcal", "597kcal"
    calorie_patterns = [
        r'(\d+(?:[.,]\d+)?)\s*(?:kcal|ккал|калорий|calories)',
        r'(?:kcal|ккал|калорий|calories|energy)[:\s]*(\d+(?:[.,]\d+)?)',
    ]
    
    for pattern in calorie_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            calories = float(match.group(1).replace(',', '.'))
            nutrition['calories'] = calories
            break
    
    # Умный парсинг: ищем все "число g" и сопоставляем с метками
    # Формат может быть:
    # "25,8 g\nprotein" или "25,8 g protein" или просто список чисел с метками ниже
    all_number_g = re.findall(r'(\d+(?:[.,]\d+)?)\s*(?:g|г)', text, re.IGNORECASE)
    all_labels = re.findall(r'\b(protein|белка|белок|proteins|fat|жиров|жир|fats|carbs|carbohydrates|углеводов|углеводы)\b', text, re.IGNORECASE)
    
    print(f"    🔍 Найдено чисел с 'g': {all_number_g}")
    print(f"    🔍 Найдено меток: {all_labels}")
    
    # Если нашли числа и метки, пытаемся сопоставить по порядку
    if all_number_g and all_labels:
        # Ищем позиции чисел и меток в тексте
        number_positions = []
        for num in all_number_g:
            for match in re.finditer(rf'{re.escape(num)}\s*(?:g|г)', text, re.IGNORECASE):
                number_positions.append((match.start(), float(num.replace(',', '.'))))
        
        label_positions = []
        for label in all_labels:
            for match in re.finditer(rf'\b{re.escape(label)}\b', text, re.IGNORECASE):
                label_positions.append((match.start(), label.lower()))
        
        # Сортируем по позиции в тексте
        number_positions.sort()
        label_positions.sort()
        
        # Сопоставляем ближайшие числа и метки
        used_numbers = set()
        used_labels = set()
        
        for num_pos, num_value in number_positions:
            # Ищем ближайшую метку после этого числа (в пределах 100 символов)
            best_match = None
            best_distance = 1000
            
            for label_pos, label_text in label_positions:
                if label_pos in used_labels:
                    continue
                    
                if label_pos > num_pos and (label_pos - num_pos) < 100:
                    distance = label_pos - num_pos
                    if distance < best_distance:
                        best_match = (label_pos, label_text)
                        best_distance = distance
            
            if best_match:
                label_pos, label_text = best_match
                if 'protein' in label_text or 'белк' in label_text:
                    if 'protein' not in nutrition:
                        nutrition['protein'] = num_value
                        used_labels.add(label_pos)
                        used_numbers.add(num_pos)
                        print(f"    ✅ Белки сопоставлены: {num_value}г (метка '{label_text}' на позиции {label_pos})")
                elif 'fat' in label_text or 'жир' in label_text:
                    if 'fats' not in nutrition:
                        nutrition['fats'] = num_value
                        used_labels.add(label_pos)
                        used_numbers.add(num_pos)
                        print(f"    ✅ Жиры сопоставлены: {num_value}г (метка '{label_text}' на позиции {label_pos})")
                elif 'carb' in label_text or 'углевод' in label_text:
                    if 'carbs' not in nutrition:
                        nutrition['carbs'] = num_value
                        used_labels.add(label_pos)
                        used_numbers.add(num_pos)
                        print(f"    ✅ Углеводы сопоставлены: {num_value}г (метка '{label_text}' на позиции {label_pos})")
    
    # Паттерны для белков (если еще не найдено умным парсингом)
    if 'protein' not in nutrition:
        protein_patterns = [
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)\s*(?:protein|белка|белок|proteins)',
            r'(?:protein|белка|белок|proteins)[:\s]*(\d+(?:[.,]\d+)?)',
            r'белк[аиы]?\s*[:\s]*(\d+(?:[.,]\d+)?)',
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=\s*(?:protein|белка|белок))',  # "25,8 g" перед "protein"
            # Ищем "число g" если в следующих 100 символах есть "protein" (включая переносы строк)
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=[\s\S]{0,100}?(?:protein|белка|белок))',
        ]
        
        for pattern in protein_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                protein = float(match.group(1).replace(',', '.'))
                nutrition['protein'] = protein
                print(f"    ✅ Белки найдены паттерном: {pattern[:50]}... -> {protein}")
                break
    
    # Паттерны для жиров (если еще не найдено умным парсингом)
    if 'fats' not in nutrition:
        fat_patterns = [
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)\s*(?:fat|жиров|жир|fats)',
            r'(?:fat|жиров|жир|fats)[:\s]*(\d+(?:[.,]\d+)?)',
            r'жир[аы]?\s*[:\s]*(\d+(?:[.,]\d+)?)',
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=\s*(?:fat|жиров|жир))',  # "24,2 g" перед "fat"
            # Ищем "число g" если в следующих 100 символах есть "fat" (включая переносы строк)
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=[\s\S]{0,100}?(?:fat|жиров|жир))',
        ]
        
        for pattern in fat_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fats = float(match.group(1).replace(',', '.'))
                nutrition['fats'] = fats
                print(f"    ✅ Жиры найдены паттерном: {pattern[:50]}... -> {fats}")
                break
    
    # Паттерны для углеводов (если еще не найдено умным парсингом)
    if 'carbs' not in nutrition:
        carbs_patterns = [
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)\s*(?:carbs|carbohydrates|углеводов|углеводы)',
            r'(?:carbs|carbohydrates|углеводов|углеводы)[:\s]*(\d+(?:[.,]\d+)?)',
            r'углевод[овы]?\s*[:\s]*(\d+(?:[.,]\d+)?)',
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=\s*(?:carbs|carbohydrates|углеводов))',  # "69,2 g" перед "carbs"
            # Ищем "число g" если в следующих 100 символах есть "carbs" (включая переносы строк)
            r'(\d+(?:[.,]\d+)?)\s*(?:g|г)(?=[\s\S]{0,100}?(?:carbs|carbohydrates|углеводов))',
        ]
        
        for pattern in carbs_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                carbs = float(match.group(1).replace(',', '.'))
                nutrition['carbs'] = carbs
                print(f"    ✅ Углеводы найдены паттерном: {pattern[:50]}... -> {carbs}")
                break
    
    # Если нашли хотя бы калории - возвращаем результат
    if nutrition:
        # Валидация значений - проверяем разумность
        # Жиры и углеводы на 100г обычно не превышают 50-60г для большинства продуктов
        fats = nutrition.get('fats', 0.0)
        carbs = nutrition.get('carbs', 0.0)
        
        # Если значения слишком высокие (>80г), вероятно ошибка распознавания
        if fats > 80:
            print(f"    ⚠️  Предупреждение: жиры = {fats}г выглядят неразумно (обычно <50г на 100г)")
            print(f"    💡 Возможно, OCR неправильно распознал значение. Проверьте исходный текст.")
        if carbs > 80:
            print(f"    ⚠️  Предупреждение: углеводы = {carbs}г выглядят неразумно (обычно <60г на 100г)")
            print(f"    💡 Возможно, OCR неправильно распознал значение. Проверьте исходный текст.")
        
        # Заполняем отсутствующие значения нулями
        return {
            'calories': nutrition.get('calories', 0.0),
            'protein': nutrition.get('protein', 0.0),
            'fats': fats,
            'carbs': carbs,
        }
    
    return None


def extract_weight_from_text(text: str) -> Optional[float]:
    """
    Извлекает вес порции из текста OCR.
    Ищет паттерны типа:
    - "270 г", "270г", "270 гр"
    - "МАССА НЕТТО 270 гр"
    - "вес: 270г"
    
    Args:
        text: Текст, распознанный через OCR
        
    Returns:
        Вес в граммах или None
    """
    if not text:
        return None
    
    # Паттерны для поиска веса
    weight_patterns = [
        r'(?:масса|вес|weight|netto|нетто)[:\s]*(\d+(?:[.,]\d+)?)\s*(?:г|g|гр|грам)',
        r'(\d+(?:[.,]\d+)?)\s*(?:г|g|гр|грам)(?=\s*(?:нетто|netto|масса|вес|weight))',
        r'(\d+(?:[.,]\d+)?)\s*(?:г|g|гр|грам)(?=\s*$)',  # В конце строки
    ]
    
    for pattern in weight_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            weight = float(match.group(1).replace(',', '.'))
            # Проверяем, что вес разумный (от 10г до 5000г)
            if 10 <= weight <= 5000:
                print(f"    ✅ Найден вес порции: {weight}г")
                return weight
    
    return None


def extract_dish_name_from_text(text: str) -> Optional[str]:
    """
    Извлекает название блюда из текста OCR.
    Обычно название блюда находится в начале текста или в крупном шрифте.
    Фильтрует лишние данные (время, статус сети и т.д.)
    
    Args:
        text: Текст, распознанный через OCR
        
    Returns:
        Название блюда или None
    """
    if not text:
        return None
    
    # Паттерны для фильтрации лишних данных
    filter_patterns = [
        r'\d{1,2}:\d{2}',  # Время "11:31"
        r'LTE|WiFi|Wi-Fi',  # Статус сети
        r'^\d+\.?\s*$',  # Только числа
        r'^\s*[•·]\s*$',  # Только маркеры
    ]
    
    # Берем первые строки как потенциальное название
    lines = text.split('\n')
    potential_name = []
    
    for i, line in enumerate(lines[:10]):  # Первые 10 строк
        line = line.strip()
        if not line or len(line) < 3:
            continue
        
        # Пропускаем строки с фильтрами
        should_skip = False
        for pattern in filter_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        # Пропускаем строки с числами и единицами (вероятно, это КБЖУ)
        if re.search(r'\d+[.,]?\d*\s*(?:kcal|ккал|g|г|калорий)', line, re.IGNORECASE):
            continue
        
        # Пропускаем очень короткие строки (меньше 3 символов)
        if len(line) < 3:
            continue
        
        # Пропускаем строки, которые выглядят как системные (только заглавные буквы и цифры)
        if re.match(r'^[A-Z0-9\s\.]+$', line) and len(line) < 10:
            continue
        
        potential_name.append(line)
        if len(potential_name) >= 2:  # Берем первые 2 подходящие строки
            break
    
    if potential_name:
        # Объединяем в название (обычно 1-2 строки)
        name = ' '.join(potential_name[:2])
        # Убираем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        # Убираем точки в конце
        name = name.rstrip('.')
        # Убираем слова-маркеры (energy, kcal, ккал и т.д.)
        name = re.sub(r'\s+(energy|kcal|ккал|калорий|calories)$', '', name, flags=re.IGNORECASE)
        # Убираем слова в конце, которые выглядят как единицы измерения
        name = re.sub(r'\s+(g|г|g\.|г\.)$', '', name, flags=re.IGNORECASE)
        if len(name) > 3:
            return name
    
    return None


def parse_menu_photo(photo_path: Path, api_key: Optional[str] = None, use_chatgpt: bool = True) -> Optional[Dict]:
    """
    Распознает меню кафе с КБЖУ из фото.
    Сначала пробует ChatGPT Vision (если доступен), затем OCR.
    
    Args:
        photo_path: Путь к фото меню
        api_key: API ключ (опционально, для OCR)
        use_chatgpt: Использовать ChatGPT Vision если доступен (по умолчанию True)
        
    Returns:
        Словарь с данными блюда или None:
        {
            'dish_name': 'Quinoa Tuna Bowl',
            'calories': 597.0,
            'protein': 25.8,
            'fats': 24.2,
            'carbs': 69.2,
            'weight': None  # Вес обычно не указан в меню
        }
    """
    if not photo_path.exists():
        print(f"    ❌ Файл не существует: {photo_path}")
        return None
    
    # 1. Пробуем Gemini Vision (самый точный)
    if GEMINI_AVAILABLE and parse_menu_with_gemini:
        gemini_result = parse_menu_with_gemini(photo_path)
        if gemini_result:
            return gemini_result
    
    # 2. Пробуем ChatGPT Vision
    if use_chatgpt and CHATGPT_AVAILABLE and parse_menu_with_chatgpt:
        openai_key = get_openai_api_key()
        if openai_key:
            result = parse_menu_with_chatgpt(photo_path, openai_key)
            if result:
                return result
            print(f"    ⚠️  ChatGPT не распознал, пробую OCR...")
    
    # Fallback: используем OCR
    if ocr_with_google_vision is None:
        print("⚠️  OCR функция недоступна. Установите зависимости.")
        return None
    
    # Получаем API ключ
    if not api_key:
        api_key = get_google_vision_api_key()
    
    try:
        # Распознаём текст с фото
        print(f"    🔍 Распознавание меню из {photo_path.name} через OCR...")
        text = ocr_with_google_vision(photo_path, api_key)
        if not text:
            print(f"    ❌ OCR не распознал текст для {photo_path.name}")
            return None
        
        print(f"    ✅ OCR распознал {len(text)} символов для {photo_path.name}")
        print(f"    📝 Полный OCR текст:")
        print(f"    {'='*60}")
        print(f"    {text}")
        print(f"    {'='*60}")
        
        # Извлекаем КБЖУ
        nutrition = extract_nutrition_from_text(text)
        if not nutrition:
            print(f"    ❌ КБЖУ не найдено в тексте меню")
            return None
        
        print(f"    ✅ КБЖУ извлечено: {nutrition}")
        
        # Извлекаем вес порции
        weight_grams = extract_weight_from_text(text)
        nutrition_per_100g = nutrition.copy()  # Сохраняем исходные значения на 100г
        
        # Если найден вес порции и КБЖУ указаны на 100г, пересчитываем
        if weight_grams and weight_grams > 0:
            # Проверяем, указаны ли КБЖУ на 100г (обычно в тексте есть "на 100г", "в 100г", "/100г")
            if re.search(r'(?:на|в|/)\s*100\s*(?:г|g|грам)', text, re.IGNORECASE):
                print(f"    📦 Найден вес порции: {weight_grams}г, КБЖУ указаны на 100г - пересчитываем...")
                multiplier = weight_grams / 100.0
                
                nutrition['calories'] = nutrition['calories'] * multiplier
                nutrition['protein'] = nutrition['protein'] * multiplier
                nutrition['fats'] = nutrition['fats'] * multiplier
                nutrition['carbs'] = nutrition['carbs'] * multiplier
                
                print(f"    ✅ Пересчитано КБЖУ для порции {weight_grams}г:")
                print(f"       Калории: {nutrition_per_100g['calories']} ккал/100г × {multiplier:.2f} = {nutrition['calories']:.1f} ккал")
                print(f"       Белки: {nutrition_per_100g['protein']}г/100г × {multiplier:.2f} = {nutrition['protein']:.1f}г")
                print(f"       Жиры: {nutrition_per_100g['fats']}г/100г × {multiplier:.2f} = {nutrition['fats']:.1f}г")
                print(f"       Углеводы: {nutrition_per_100g['carbs']}г/100г × {multiplier:.2f} = {nutrition['carbs']:.1f}г")
            else:
                print(f"    📦 Найден вес порции: {weight_grams}г, но КБЖУ указаны для всей порции")
                # Если КБЖУ указаны для всей порции, то nutrition_per_100g нужно пересчитать обратно
                if weight_grams > 0:
                    multiplier = 100.0 / weight_grams
                    nutrition_per_100g = {
                        'calories': nutrition['calories'] * multiplier,
                        'protein': nutrition['protein'] * multiplier,
                        'fats': nutrition['fats'] * multiplier,
                        'carbs': nutrition['carbs'] * multiplier,
                    }
        
        # Извлекаем название блюда
        dish_name = extract_dish_name_from_text(text)
        if dish_name:
            print(f"    ✅ Название блюда: {dish_name}")
        else:
            dish_name = "Блюдо из меню"
            print(f"    ⚠️  Название блюда не распознано, используется: {dish_name}")
        
        return {
            'dish_name': dish_name,
            'calories': nutrition['calories'],
            'protein': nutrition['protein'],
            'fats': nutrition['fats'],
            'carbs': nutrition['carbs'],
            'weight': weight_grams,  # Вес порции в граммах
            'nutrition_per_100g': nutrition_per_100g,  # Сохраняем исходные значения на 100г
            'source': 'menu_ocr',
        }
        
    except Exception as e:
        print(f"❌ Ошибка при распознавании меню из {photo_path.name}: {e}")
        return None

