#!/usr/bin/env python3
"""
Утилита для вычисления возраста из даты рождения
Используется для обновления документов с актуальным возрастом
"""

from datetime import datetime
from pathlib import Path
import json


def calculate_age(birth_date_str: str, reference_date: datetime = None) -> int:
    """
    Вычисляет возраст из даты рождения
    
    Args:
        birth_date_str: Дата рождения в формате YYYY-MM-DD или DD.MM.YYYY
        reference_date: Дата для расчета возраста (по умолчанию - сегодня)
    
    Returns:
        Возраст в годах
    """
    if reference_date is None:
        reference_date = datetime.now()
    
    # Парсим дату рождения
    if '-' in birth_date_str:
        birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d')
    elif '.' in birth_date_str:
        birth_date = datetime.strptime(birth_date_str, '%d.%m.%Y')
    else:
        raise ValueError(f"Неизвестный формат даты: {birth_date_str}")
    
    # Вычисляем возраст
    age = reference_date.year - birth_date.year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    
    return age


def get_patient_info() -> dict:
    """Загружает информацию о пациенте из knowledge_base.json"""
    kb_path = Path(__file__).parent.parent / "knowledge_base.json"
    
    if not kb_path.exists():
        return {}
    
    with open(kb_path, 'r', encoding='utf-8') as f:
        kb = json.load(f)
    
    return kb.get('patient_info', {})


def main():
    """Основная функция"""
    patient_info = get_patient_info()
    
    if not patient_info:
        print("❌ Информация о пациенте не найдена в knowledge_base.json")
        return
    
    birth_date = patient_info.get('birth_date') or patient_info.get('birth_date_formatted')
    if not birth_date:
        print("❌ Дата рождения не найдена")
        return
    
    name = patient_info.get('name', 'Пациент')
    
    # Вычисляем возраст на сегодня
    age_today = calculate_age(birth_date)
    
    # Вычисляем возраст на день рождения в этом году
    today = datetime.now()
    birth_date_obj = datetime.strptime(birth_date, '%Y-%m-%d') if '-' in birth_date else datetime.strptime(birth_date, '%d.%m.%Y')
    birthday_this_year = datetime(today.year, birth_date_obj.month, birth_date_obj.day)
    
    # Возраст после следующего дня рождения
    if today >= birthday_this_year:
        # День рождения уже прошел в этом году
        age_after_birthday = age_today + 1
        next_birthday_year = today.year + 1
    else:
        # День рождения еще не наступил
        age_after_birthday = age_today + 1
        next_birthday_year = today.year
    
    print("=" * 60)
    print(f"ИНФОРМАЦИЯ О ПАЦИЕНТЕ: {name}")
    print("=" * 60)
    print(f"Дата рождения: {birth_date}")
    print(f"Сегодня ({today.strftime('%Y-%m-%d')}): {age_today} лет")
    print(f"После {birth_date_obj.strftime('%d.%m')}.{next_birthday_year}: {age_after_birthday} лет")
    print()
    print(f"📅 Следующий день рождения: {birth_date_obj.strftime('%d.%m')}.{next_birthday_year}")
    print(f"   В этот день возраст будет: {age_after_birthday} лет")


if __name__ == "__main__":
    main()

