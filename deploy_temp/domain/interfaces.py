from abc import ABC, abstractmethod
from datetime import date
from typing import Optional, List, Dict
from .models import DayLog, MealItem

class NutritionRepository(ABC):
    """Интерфейс для работы с хранилищем питания"""
    
    @abstractmethod
    def get_day(self, day_date: date) -> Optional[DayLog]:
        """Получить лог за день"""
        pass
    
    @abstractmethod
    def save_day(self, log: DayLog) -> None:
        """Сохранить лог"""
        pass
    
    @abstractmethod
    def get_period(self, start_date: date, end_date: date) -> List[DayLog]:
        """Получить логи за период"""
        pass

class VisionService(ABC):
    """Интерфейс для распознавания еды"""
    
    @abstractmethod
    def analyze_food(self, image_path: str, hint: str = None) -> List[MealItem]:
        """Распознать еду по фото"""
        pass
