"""
Database save functions - PostgreSQL Version

Заменяет save_meal_to_json и save_weight_measurement
для работы с PostgreSQL вместо JSON.
Время и дата при сохранении — по Москве (UTC+3).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

MSK = timezone(timedelta(hours=3))

from database import SessionLocal, create_nutrition_log, create_weight, create_supplement_log, create_body_measurement

logger = logging.getLogger(__name__)


# ── Canonical item schema for nutrition_log.items JSONB ──────────────────────
# The storage format is {food, amount, unit, calories, protein, fats, carbs, fiber}.
# Internal domain code uses {product, weight_g, ...}.
# Historical data also contains {name, weight_g, ...} and {name, weight, ...}.
# This normaliser is the SINGLE source of truth for translation — every writer
# into nutrition_log.items MUST go through it.


def normalize_item_to_canonical(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate any known input dialect to the canonical DB item schema.

    Accepted input keys (first non-empty wins):
        name       : "product" | "name" | "food"
        weight     : "weight_g" | "amount" | "weight"
        kcal/macros: "calories" | "protein" | "fats" | "fat" | "carbs" | "fiber"
        note       : "note"  (optional, pass-through)
        drinks     : "drinks"  (optional, pass-through)

    Returns:
        Canonical dict:
            {
              "food":     str,
              "amount":   float,
              "unit":     "г",
              "calories": int,
              "protein": int,
              "fats": int,
              "carbs": int,
              "fiber":    float (1 decimal),
              # optional:
              "note":     str,
              "drinks":   float,
            }
    """
    food = item.get("product") or item.get("name") or item.get("food") or "Неизвестный продукт"
    amount = (
        item.get("weight_g")
        if item.get("weight_g") is not None
        else item.get("amount")
        if item.get("amount") is not None
        else item.get("weight")
    )
    amount = float(amount or 0.0)

    # Tolerate both "fat" (singular, old schema) and "fats" (plural, canonical)
    fats_raw = item.get("fats") if item.get("fats") is not None else item.get("fat", 0)

    canonical = {
        "food": str(food),
        "amount": amount,
        "unit": "г",
        "calories": int(round(float(item.get("calories") or 0))),
        "protein": int(round(float(item.get("protein") or 0))),
        "fats": int(round(float(fats_raw or 0))),
        "carbs": int(round(float(item.get("carbs") or 0))),
        "fiber": round(float(item.get("fiber") or 0), 1),
    }

    # Pass-through optional fields (preserve if present & non-empty)
    if item.get("note"):
        canonical["note"] = str(item["note"])
    if item.get("drinks") is not None:
        canonical["drinks"] = float(item["drinks"])

    return canonical


def save_meal_to_db(meal_data: dict, meal_name: str = None, user_id: int = 895655) -> bool:
    """
    Сохраняет приём пищи в PostgreSQL

    Args:
        meal_data: Данные о приёме пищи из состояния
        meal_name: Название приёма пищи
        user_id: Telegram ID пользователя

    Returns:
        True if successful
    """
    try:
        # Определяем дату
        custom_date = meal_data.get("date")
        if custom_date:
            if isinstance(custom_date, str):
                meal_date = datetime.strptime(custom_date, "%Y-%m-%d").date()
            else:
                meal_date = custom_date
        else:
            meal_date = datetime.now(MSK).date()

        # Определяем время (по Москве)
        meal_time_str = meal_data.get("meal_time", datetime.now(MSK).strftime("%H:%M"))
        try:
            meal_time = datetime.strptime(meal_time_str, "%H:%M").time()
        except:
            meal_time = datetime.now(MSK).time()

        # Название приёма пищи
        if not meal_name:
            meal_name = meal_data.get("dish_name") or meal_data.get("meal_name") or "Приём пищи"

        # Формируем items
        # Enrich with fiber fallback before serialization — LLM may omit fiber
        # for some items, and fiber_table gives us a reasonable default from
        # product name + weight. Idempotent for items that already have fiber.
        from core.food.fiber_table import enrich_items_with_fiber, sum_fiber

        meal_items = meal_data.get("meal_items", [])
        enrich_items_with_fiber(meal_items)

        # Single normalisation path — all writers of nutrition_log.items go through this
        items = [normalize_item_to_canonical(item) for item in meal_items]

        # Totals — recompute fiber from enriched items to avoid drift.
        meal_totals = meal_data.get("meal_totals", {})
        totals = {
            "calories": int(round(meal_totals.get("calories", 0.0))),
            "protein": int(round(meal_totals.get("protein", 0.0))),
            "fats": int(round(meal_totals.get("fats", 0.0))),
            "carbs": int(round(meal_totals.get("carbs", 0.0))),
            "fiber": sum_fiber(items),
        }

        # Фото
        photo_paths = meal_data.get("photo_paths", [])
        if isinstance(photo_paths, list):
            photo_paths = [str(p) for p in photo_paths]
        else:
            photo_paths = []

        # Сохраняем в БД
        db = SessionLocal()
        try:
            create_nutrition_log(
                db,
                user_id=user_id,
                date=meal_date,
                meal_time=meal_time,
                meal_name=meal_name,
                items=items,
                totals=totals,
                photo_paths=photo_paths,
            )
            logger.info(f"Meal saved to DB: {meal_name} on {meal_date} at {meal_time}")
            return True
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error saving meal to DB: {e}", exc_info=True)
        return False


def save_weight_to_db(data: Dict[str, Any], user_id: int = 895655) -> str:
    """
    Saves a weight measurement to PostgreSQL

    Args:
        data: Dict containing weight, date, source, etc.
        user_id: Telegram ID пользователя

    Returns:
        String confirmation or empty string on error
    """
    try:
        # Определяем дату и время
        date_input = data.get("date")
        if not date_input:
            measured_at = datetime.now()
        else:
            date_str = str(date_input)

            # Парсинг даты
            try:
                if "T" in date_str:
                    measured_at = datetime.fromisoformat(date_str)
                elif " " in date_str and ":" in date_str:
                    # "2025-08-03 09:27"
                    measured_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                elif len(date_str) == 10 and "-" in date_str:
                    # "2025-08-03"
                    measured_at = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    measured_at = datetime.now()
            except:
                measured_at = datetime.now()

        # Извлекаем данные
        weight = data.get("weight")
        body_fat = data.get("body_fat")
        muscle_mass = data.get("muscle_mass")
        water = data.get("water")
        bmi = data.get("bmi")
        visceral_fat = data.get("visceral_fat")
        bone_mass = data.get("bone_mass")
        source = data.get("source", "manual")

        # Сохраняем в БД
        db = SessionLocal()
        try:
            create_weight(
                db,
                user_id=user_id,
                measured_at=measured_at,
                weight=weight,
                body_fat=body_fat,
                muscle_mass=muscle_mass,
                water=water,
                bmi=bmi,
                visceral_fat=visceral_fat,
                bone_mass=bone_mass,
                source=source,
            )
            logger.info(f"Weight saved to DB: {weight}kg on {measured_at}")
            return f"Saved to DB: {measured_at.strftime('%Y-%m-%d %H:%M')}"
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error saving weight to DB: {e}", exc_info=True)
        return ""


def save_supplements_to_db(items: list, user_id: int = 895655, date_str: Optional[str] = None) -> bool:
    """
    Сохраняет добавки в PostgreSQL

    Args:
        items: Список названий добавок
        user_id: Telegram ID пользователя
        date_str: Дата в формате YYYY-MM-DD (если None - сегодня)

    Returns:
        True if successful
    """
    if not items:
        return False

    try:
        # Дата
        if date_str:
            supplement_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            supplement_date = datetime.now().date()

        # Время
        supplement_time = datetime.now().time()

        # Сохраняем
        db = SessionLocal()
        try:
            for item in items:
                create_supplement_log(
                    db, user_id=user_id, date=supplement_date, time=supplement_time, supplement_name=item, dosage=None
                )
            logger.info(f"Supplements saved to DB: {items}")
            return True
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error saving supplements to DB: {e}", exc_info=True)
        return False


def save_body_measurement_to_db(data: Dict[str, Any], user_id: int = 895655) -> bool:
    """
    Сохраняет замеры тела в PostgreSQL и JSON
    """
    try:
        # 1. Сначала сохраняем в JSON (как исторически сложилось)
        save_body_measurement_to_json(data)

        # 2. Сохраняем в PostgreSQL
        date_input = data.get("date")
        if not date_input:
            measurement_date = datetime.now(MSK).date()
        else:
            try:
                measurement_date = datetime.strptime(str(date_input), "%Y-%m-%d").date()
            except:
                measurement_date = datetime.now(MSK).date()

        db = SessionLocal()
        try:
            create_body_measurement(
                db,
                user_id=user_id,
                date=measurement_date,
                waist_cm=data.get("waist_cm"),
                neck_cm=data.get("neck_cm"),
                hips_cm=data.get("hips_cm"),
                chest_cm=data.get("chest_cm"),
                thigh_cm=data.get("thigh_cm"),
                biceps_cm=data.get("biceps_cm"),
                notes=data.get("notes"),
            )
            logger.info(f"Body measurement saved to DB for {measurement_date}")
            return True
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error saving body measurement: {e}", exc_info=True)
        return False


def save_body_measurement_to_json(data: Dict[str, Any]):
    """Сохраняет замеры в data/weights/body_measurements.json"""
    import json
    import os

    file_path = "data/weights/body_measurements.json"

    # Схемы полей
    field_map = {
        "waist_cm": "waist_navel_cm",
        "neck_cm": "neck_adams_apple_cm",
        "hips_cm": "hips_buttocks_cm",
        "chest_cm": "chest_nipples_cm",
        "thigh_cm": "thigh_mid_cm",
        "biceps_cm": "bicep_mid_cm",
    }

    # Новая запись
    entry = {"date": data.get("date") or datetime.now().strftime("%Y-%m-%d")}
    for llm_key, json_key in field_map.items():
        if data.get(llm_key) is not None:
            entry[json_key] = data[llm_key]
    if data.get("notes"):
        entry["notes"] = data["notes"]

    # Загружаем
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                content = json.load(f)
            except:
                content = {"entries": []}
    else:
        content = {"entries": []}

    if "entries" not in content:
        content["entries"] = []

    # Предотвращаем дубли по дате
    content["entries"] = [e for e in content["entries"] if e.get("date") != entry["date"]]
    content["entries"].insert(0, entry)

    # Сохраняем
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
