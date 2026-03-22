"""Proxy: core.nutrition → core.food.nutrition (рефакторинг 22.03.2026)"""
from core.food.nutrition import *  # noqa: F401,F403
from core.food.nutrition import process_llm_food_data, process_meal_description_with_menu  # explicit re-exports
