
import os
import math
from typing import Dict, Tuple, Optional

# Значения по умолчанию (можно переопределить через ENV)
DEFAULT_WEIGHT_KG = 82.0
DEFAULT_PROTEIN_PER_KG = 1.8
DEFAULT_FAT_PER_KG_MIN = 0.7
DEFAULT_FAT_PER_KG_MAX = 0.9
DEFAULT_DEFICIT_PCT = 0.15  # 15%

def get_user_settings() -> Dict:
    """Получает настройки пользователя из переменных окружения или дефолтные"""
    return {
        'weight_kg': float(os.getenv('TARGET_WEIGHT_KG', DEFAULT_WEIGHT_KG)),
        'protein_per_kg': float(os.getenv('TARGET_PROTEIN_PER_KG', DEFAULT_PROTEIN_PER_KG)),
        'fat_per_kg_min': float(os.getenv('TARGET_FAT_PER_KG_MIN', DEFAULT_FAT_PER_KG_MIN)),
        'fat_per_kg_max': float(os.getenv('TARGET_FAT_PER_KG_MAX', DEFAULT_FAT_PER_KG_MAX)),
        'deficit_pct': float(os.getenv('TARGET_DEFICIT_PCT', DEFAULT_DEFICIT_PCT)),
    }

def calculate_targets(avg_tdee: Optional[float] = None, stats: Optional[Dict] = None) -> Dict:
    """
    Рассчитывает целевые калории и макросы.
    Можно передать avg_tdee напрямую или словарь stats от garmin_data.
    Если данных нет или они слишком низкие (<1500), используются Fallback значения.
    """
    settings = get_user_settings()
    weight = settings['weight_kg']
    deficit_pct = settings['deficit_pct']
    
    # Fallback Values (для мужчины 48 лет, 82 кг, ~170 см)
    # BMR Mifflin-St Jeor: ~1750 + активность. Garmin BMR обычно ~1950 (включает бытовую?)
    FALLBACK_BMR = 1950
    FALLBACK_ACTIVE = 400
    FALLBACK_TDEE = FALLBACK_BMR + FALLBACK_ACTIVE  # 2350
    
    estimated_tdee = 0.0
    
    if stats and stats.get('total', 0) > 1500:
        estimated_tdee = stats['total']
    elif avg_tdee and avg_tdee > 1500:
        estimated_tdee = avg_tdee
    else:
        # Если данных нет, используем Fallback
        estimated_tdee = FALLBACK_TDEE
        
    # 1. Считаем целевые калории
    target_calories = round(estimated_tdee * (1 - deficit_pct))
    
    # Проверка на максимальный дефицит (безопасность)
    max_deficit = 800
    actual_deficit = estimated_tdee - target_calories
    if actual_deficit > max_deficit:
        target_calories = round(estimated_tdee - max_deficit)
        
    # Проверка на превышение TDEE
    if target_calories > estimated_tdee:
        target_calories = round(estimated_tdee)
        
    # 2. Считаем макросы
    # Белки - фиксировано от веса
    protein_g = round(weight * settings['protein_per_kg'])
    
    # Жиры - берем минимум для начала
    fats_g = round(weight * settings['fat_per_kg_min'])
    
    # Углеводы - остаток
    calories_from_protein = protein_g * 4
    calories_from_fats = fats_g * 9
    remaining_kcal_for_carbs = target_calories - calories_from_protein - calories_from_fats
    carbs_g = math.floor(remaining_kcal_for_carbs / 4)
    
    # Корректировка если углеводов меньше нуля
    if carbs_g < 0:
        # План Б: Снижаем жиры до абсолютного минимума (50г или 0.5г/кг)
        min_fats = max(50, round(weight * 0.5))
        if fats_g > min_fats:
            fats_g = min_fats
            calories_from_fats = fats_g * 9
            remaining_kcal_for_carbs = target_calories - calories_from_protein - calories_from_fats
            carbs_g = math.floor(remaining_kcal_for_carbs / 4)
            
    if carbs_g < 0:
        # План В: Снижаем белок до 1.6
        min_protein_per_kg = 1.6
        new_protein = round(weight * min_protein_per_kg)
        if protein_g > new_protein:
            protein_g = new_protein
            calories_from_protein = protein_g * 4
            remaining_kcal_for_carbs = target_calories - calories_from_protein - calories_from_fats
            carbs_g = math.floor(remaining_kcal_for_carbs / 4)
            
    # Если всё равно минус, ставим 0 (значит калорий слишком мало)
    if carbs_g < 0:
        carbs_g = 0
        
    return {
        'calories': target_calories,
        'protein': protein_g,
        'fats': fats_g,
        'carbs': carbs_g,
        'avg_tdee': round(estimated_tdee)
    }

def check_feasibility(remaining_calories: float, remaining_protein: float) -> Optional[str]:
    """
    Проверяет, реально ли набрать оставшийся белок в рамках оставшихся калорий.
    Возвращает предупреждение, если нереально.
    """
    if remaining_calories <= 0:
        if remaining_protein > 5:
            return f"⚠️ Калории закончились, а белка нужно еще {remaining_protein:.0f}г!"
        return None
        
    # Максимум белка, который теоретически можно уместить в калории (если есть чистый белок)
    # 1г белка = 4 ккал
    max_protein_possible = math.floor(remaining_calories / 4)
    
    if remaining_protein > max_protein_possible:
        diff = remaining_protein - max_protein_possible
        return (
            f"⚠️ Цель по белку недостижима в рамках калорий.\n"
            f"Осталось {remaining_calories:.0f} ккал, это максимум {max_protein_possible} г белка (чистого).\n"
            f"Не хватает {diff:.0f} г. Рекомендую обезжиренный творог, тунец или протеин на воде."
        )
        
    # Если белок составляет очень большую часть оставшихся калорий (>70%)
    protein_ratio = (remaining_protein * 4) / remaining_calories
    if protein_ratio > 0.7:
        return (
            f"⚠️ Нужно наедать белок! Он займет {protein_ratio*100:.0f}% оставшихся калорий.\n"
            f"Выбирай самые нежирные источники: креветки, белок яйца, грудка, треска."
        )
        
    return None
