#!/usr/bin/env python3
"""
Единая функция для загрузки Google Vision API ключа
Используется во всех модулях для консистентности
"""

import os
from pathlib import Path
from typing import Optional


def load_google_vision_api_key() -> Optional[str]:
    """
    Загружает Google Vision API ключ из различных источников.
    
    Приоритет:
    1. Переменная окружения GOOGLE_VISION_API_KEY
    2. Файл .google_vision_api_key в корне HealthVault
    3. Файл ~/FamilyDocs/.google_vision_api_key
    
    Returns:
        API ключ или None, если не найден
    """
    # 1. Проверяем переменную окружения
    api_key = os.getenv('GOOGLE_VISION_API_KEY')
    if api_key and api_key.strip() and api_key != "your_google_vision_key_here":
        api_key = api_key.strip()
        if len(api_key) > 20:  # Минимальная длина валидного ключа
            return api_key
    
    # 2. Проверяем файл в корне HealthVault
    healthvault_root = Path(__file__).parent.parent.parent
    key_file = healthvault_root / '.google_vision_api_key'
    
    if key_file.exists():
        try:
            api_key = key_file.read_text().strip()
            if api_key and api_key != "your_google_vision_key_here" and len(api_key) > 20:
                return api_key
        except Exception as e:
            print(f"⚠️  Ошибка чтения ключа из HealthVault: {e}")
    
    # 3. Проверяем файл в FamilyDocs
    family_docs_key = Path.home() / "FamilyDocs" / ".google_vision_api_key"
    if family_docs_key.exists():
        try:
            api_key = family_docs_key.read_text().strip()
            if api_key and api_key != "your_google_vision_key_here" and len(api_key) > 20:
                print(f"📋 Используется API ключ из FamilyDocs")
                return api_key
        except Exception as e:
            print(f"⚠️  Ошибка чтения ключа из FamilyDocs: {e}")
    
    return None


def get_google_vision_api_key(provided_key: Optional[str] = None) -> Optional[str]:
    """
    Получает API ключ, используя переданный ключ или загружая из источников.
    
    Args:
        provided_key: Ключ, переданный явно (имеет приоритет)
        
    Returns:
        API ключ или None
    """
    # Если ключ передан явно - используем его
    if provided_key and provided_key.strip() and provided_key != "your_google_vision_key_here":
        api_key = provided_key.strip()
        if len(api_key) > 20:
            return api_key
    
    # Иначе загружаем из источников
    return load_google_vision_api_key()




