#!/usr/bin/env python3
"""
Модели данных для системы управления состоянием.
Используют Pydantic для типизации и валидации.
"""

from pydantic import BaseModel, Field
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


class MealConfirmationData(BaseModel):
    """
    Данные состояния при подтверждении приёма пищи.

    Используется в состоянии 'waiting_confirmation'.
    """

    description: str = Field(..., description="Описание приёма пищи")
    meal_items: List[Dict[str, Any]] = Field(..., description="Распознанные продукты")
    meal_totals: Dict[str, float] = Field(..., description="Суммарное КБЖУ")
    meal_time: Optional[str] = Field(None, description="Время приёма пищи (HH:MM)")
    meal_name: Optional[str] = Field(None, description="Название приёма (Завтрак, Обед)")
    date: Optional[str] = Field(None, description="Дата если не сегодня (YYYY-MM-DD)")

    class Config:
        json_schema_extra = {
            "example": {
                "description": "Куриная грудка с рисом",
                "meal_items": [
                    {"product": "Куриная грудка", "weight_g": 150, "calories": 248},
                    {"product": "Рис", "weight_g": 100, "calories": 130},
                ],
                "meal_totals": {"calories": 378, "protein": 45, "fats": 5, "carbs": 28},
                "meal_name": "Обед",
            }
        }


# Вспомогательные функции для конвертации


def dict_to_menu_data(data: Optional[Dict]) -> Optional[MenuData]:
    """
    Конвертировать словарь в MenuData, с валидацией.

    Args:
        data: Словарь с данными меню или None

    Returns:
        MenuData объект или None если данные отсутствуют

    Raises:
        ValidationError: Если данные не соответствуют схеме
    """
    if data is None:
        return None
    return MenuData(**data)


def menu_data_to_dict(menu_data: Optional[MenuData]) -> Optional[Dict]:
    """
    Конвертировать MenuData в словарь для хранения в UserState.

    Args:
        menu_data: MenuData объект или None

    Returns:
        Словарь или None
    """
    if menu_data is None:
        return None
    return menu_data.model_dump()


def dict_to_photo_state_data(data: Dict) -> PhotoStateData:
    """
    Конвертировать словарь в PhotoStateData с валидацией.

    Args:
        data: Словарь с данными состояния фото

    Returns:
        PhotoStateData объект

    Raises:
        ValidationError: Если обязательные поля отсутствуют
    """
    # Если menu_data есть и это dict, конвертировать в MenuData
    if "menu_data" in data and data["menu_data"] is not None:
        if isinstance(data["menu_data"], dict):
            data["menu_data"] = MenuData(**data["menu_data"])

    return PhotoStateData(**data)
