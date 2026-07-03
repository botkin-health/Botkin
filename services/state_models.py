#!/usr/bin/env python3
"""
Модели данных для системы управления состоянием.
Используют Pydantic для типизации и валидации.
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any


class MenuData(BaseModel):
    """
    Данные о распознанном меню/блюде из изображения.

    КРИТИЧНО: Эти данные НЕ ДОЛЖНЫ теряться при пересоздании состояния!
    """

    dish_name: str = Field(..., description="Название блюда")
    calories: float = Field(..., ge=0, description="Калории (ккал)")
    protein: float = Field(..., ge=0, description="Белки (г)")
    fats: float = Field(..., ge=0, description="Жиры (г")
    carbs: float = Field(..., ge=0, description="Углеводы (г)")
    weight: Optional[int] = Field(None, ge=0, description="Вес порции (г)")
    nutrition_per_100g: Optional[Dict[str, float]] = Field(None, description="КБЖУ на 100г")
    components: Optional[List[Dict[str, Any]]] = Field(None, description="Компоненты блюда")
    source: Optional[str] = Field(None, description="Источник распознавания: chatgpt_vision, gemini_vision, ocr")
    raw_text: Optional[str] = Field(None, description="Сырой текст из OCR")
    nutrition_not_found: Optional[bool] = Field(False, description="Флаг что КБЖУ не найдено")

    class Config:
        json_schema_extra = {
            "example": {
                "dish_name": "Рыбные кебабы с гарниром",
                "calories": 500.0,
                "protein": 33.0,
                "fats": 13.0,
                "carbs": 61.0,
                "weight": 415,
                "source": "chatgpt_vision",
            }
        }


class PhotoStateData(BaseModel):
    """
    Данные состояния при обработке фото.

    Используется в состоянии 'waiting_description'.
    """

    photo_paths: List[str] = Field(..., description="Пути к фото на диске")
    photo_file_ids: List[str] = Field(..., description="Telegram file IDs")
    caption: str = Field(default="", description="Подпись пользователя")
    menu_data: Optional[MenuData] = Field(
        None, description="КРИТИЧНО: Распознанное КБЖУ - НЕ ТЕРЯТЬ при пересоздании состояния!"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "photo_paths": ["/app/data/photos/user123_20240209.jpg"],
                "photo_file_ids": ["AgACAgIAAxkBAAI..."],
                "caption": "ужин",
                "menu_data": {
                    "dish_name": "Салат Цезарь",
                    "calories": 350.0,
                    "protein": 25.0,
                    "fats": 18.0,
                    "carbs": 20.0,
                },
            }
        }


class MealStateData(BaseModel):
    """
    Данные состояния meal-flow (приём пищи ожидает подтверждения).

    Используется в состоянии 'waiting_confirmation' (одиночный приём пищи,
    не multi_meals-ветка). extra="forbid" — ловит опечатку в имени ключа
    (например "photo_path" вместо "photo_paths", #256) в момент создания
    состояния, а не тихой потерей данных при чтении в save_meal_to_db() (#258).
    """

    model_config = ConfigDict(extra="forbid")

    meal_items: List[Dict[str, Any]] = Field(..., description="Позиции приёма пищи")
    meal_totals: Dict[str, float] = Field(..., description="КБЖУ итого")
    meal_name: Optional[str] = Field(None, description="Название приёма пищи")
    dish_name: Optional[str] = Field(None, description="Название блюда (menu-флоу)")
    meal_time: Optional[str] = Field(None, description="Время приёма пищи HH:MM")
    description: Optional[str] = Field(None, description="Исходное описание/подпись пользователя")
    source: Optional[str] = Field(None, description="Источник: text, photo, ocr_db_lookup")
    date: Optional[str] = Field(None, description="Дата приёма пищи YYYY-MM-DD")
    photo_paths: List[str] = Field(default_factory=list, description="Пути к фото на диске")
    portion_multiplier: Optional[float] = Field(None, description="Deprecated")
    menu_ocr: Optional[bool] = Field(None, description="Флаг что это меню, распознанное по фото")


# Вспомогательные функции для конвертации
