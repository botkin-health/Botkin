from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class MacroStats(BaseModel):
    """Базовая модель для КБЖУ"""
    calories: float = Field(default=0.0, description="Калории (ккал)")
    protein: float = Field(default=0.0, description="Белки (г)")
    fats: float = Field(default=0.0, description="Жиры (г)")
    carbs: float = Field(default=0.0, description="Углеводы (г)")
    fiber: Optional[float] = Field(default=None, description="Клетчатка (г)")

    @property
    def is_empty(self) -> bool:
        return self.calories == 0 and self.protein == 0 and self.fats == 0 and self.carbs == 0

class MealItem(MacroStats):
    """Продукт или компонент приема пищи"""
    model_config = {"populate_by_name": True}
    
    name: str = Field(..., alias="food", description="Название продукта")
    amount: Optional[float] = Field(default=None, description="Количество")
    unit: str = Field(default="г", description="Единица измерения (г, мл, шт)")
    weight_g: Optional[float] = Field(default=None, description="Вес в граммах (для расчетов)")
    note: Optional[str] = Field(default=None, description="Заметка пользователя")
    
    # Служебные поля
    source: Optional[str] = Field(default=None, description="Источник (ocr, manual, search)")
    is_estimated: bool = Field(default=False, description="Если вес был оценен приблизительно")

    @field_validator('amount', mode='before')
    def parse_amount(cls, v):
        if v is None or v == "":
            return None
        return float(v)

class Meal(BaseModel):
    """Прием пищи (Завтрак, Обед, и т.д.)"""
    model_config = {"populate_by_name": True}
    
    name: str = Field(..., alias="meal", description="Название приема (Завтрак, Обед...)")
    time: str = Field(..., description="Время приема HH:MM")
    items: List[MealItem] = Field(default_factory=list)
    totals: Optional[MacroStats] = None
    
    def calculate_totals(self) -> MacroStats:
        """Пересчитывает итоги по items"""
        stats = MacroStats()
        for item in self.items:
            stats.calories += item.calories
            stats.protein += item.protein
            stats.fats += item.fats
            stats.carbs += item.carbs
            if item.fiber:
                stats.fiber = (stats.fiber or 0) + item.fiber
        
        # Округляем
        stats.calories = round(stats.calories, 1)
        stats.protein = round(stats.protein, 1)
        stats.fats = round(stats.fats, 1)
        stats.carbs = round(stats.carbs, 1)
        if stats.fiber:
            stats.fiber = round(stats.fiber, 1)
            
        self.totals = stats
        return stats

class DayGoals(BaseModel):
    """Цели на день"""
    calories: float
    protein: float
    fats: float
    carbs: Optional[float] = None

class DayLog(BaseModel):
    """Полная запись за день"""
    date: date
    meals: List[Meal] = Field(default_factory=list)
    had_workout: bool = False
    totals: Optional[MacroStats] = None
    targets: Optional[DayGoals] = None
    
    def recalculate_totals(self):
        """Пересчитывает итоги дня"""
        day_stats = MacroStats()
        for meal in self.meals:
            meal_stats = meal.calculate_totals()
            day_stats.calories += meal_stats.calories
            day_stats.protein += meal_stats.protein
            day_stats.fats += meal_stats.fats
            day_stats.carbs += meal_stats.carbs
            if meal_stats.fiber:
                day_stats.fiber = (day_stats.fiber or 0) + meal_stats.fiber
        
        # Округляем
        day_stats.calories = round(day_stats.calories, 1)
        day_stats.protein = round(day_stats.protein, 1)
        day_stats.fats = round(day_stats.fats, 1)
        day_stats.carbs = round(day_stats.carbs, 1)
        
        self.totals = day_stats

class WeeklyStats(BaseModel):
    """Статистика за неделю"""
    start_date: date
    end_date: date
    days_logged: int
    total_stats: MacroStats
    average_stats: MacroStats
    best_day: Optional[date] = None
    worst_day: Optional[date] = None

