import json
import logging
from pathlib import Path
from typing import List, Optional
from datetime import date

from domain.models import DayLog
from domain.interfaces import NutritionRepository
from config import get_settings

logger = logging.getLogger(__name__)


class JsonNutritionRepository(NutritionRepository):
    """
    Реализация репозитория на основе JSON файла.
    Без file locking (по требованию пользователя).
    """

    def __init__(self, file_path: Optional[Path] = None):
        settings = get_settings()
        if file_path:
            self.file_path = file_path
        else:
            self.file_path = settings.data_dir / "nutrition" / "nutrition_log.json"

        # Гарантируем, что директория существует
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_json(self) -> dict:
        """Читает весь JSON файл"""
        if not self.file_path.exists():
            return {"entries": []}

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {self.file_path}")
            return {"entries": []}

    def _write_json(self, data: dict):
        """Пишет весь JSON файл"""
        # Создаем бэкап перед записью (на всякий случай, раз нет локов)
        backup_path = self.file_path.parent / f"{self.file_path.name}.bak"
        if self.file_path.exists():
            import shutil

            shutil.copy2(self.file_path, backup_path)

        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_day(self, day_date: date) -> Optional[DayLog]:
        """Получить лог за день"""
        data = self._read_json()
        target_date_str = day_date.isoformat()

        for entry in data.get("entries", []):
            if entry.get("date") == target_date_str:
                try:
                    return DayLog(**entry)
                except Exception as e:
                    logger.error(f"Error parsing day log for {target_date_str}: {e}")
                    return None
        return None

    def save_day(self, log: DayLog) -> None:
        """Сохранить или обновить лог за день"""
        data = self._read_json()
        target_date_str = log.date.isoformat()
        entries = data.get("entries", [])

        # Конвертируем модель в словарь
        # exclude_none=True может быть опасно, если поля нужны для UI
        # Идем безопасным путем: dump mode='json'
        log_dict = log.model_dump(mode="json")

        updated = False
        for i, entry in enumerate(entries):
            if entry.get("date") == target_date_str:
                entries[i] = log_dict
                updated = True
                break

        if not updated:
            entries.append(log_dict)
            # Сортируем по дате
            entries.sort(key=lambda x: x["date"])

        data["entries"] = entries
        self._write_json(data)
        logger.info(f"Saved nutrition log for {target_date_str}")

    def get_period(self, start_date: date, end_date: date) -> List[DayLog]:
        """Получить список логов за период (включительно)"""
        data = self._read_json()
        result = []

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        for entry in data.get("entries", []):
            entry_date = entry.get("date")
            if start_str <= entry_date <= end_str:
                try:
                    result.append(DayLog(**entry))
                except Exception:
                    continue

        return result
