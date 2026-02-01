#!/usr/bin/env python3
"""
Скрипт миграции первичных данных на Google Drive.
Переименовывает файлы по конвенции: {тип}_{дата}_{источник}_{детали}.{ext}
"""

import os
import shutil
import re
from pathlib import Path
from datetime import datetime

# Пути
SOURCE_DATA = Path("/Users/alexlyskovsky/HealthVault/data")
DRIVE_ROOT = Path("/Users/alexlyskovsky/My Drive/HealthVault")

# Целевые папки
ALEXANDER_DIR = DRIVE_ROOT / "Александр"
VALERIA_DIR = DRIVE_ROOT / "Валерия"
GARMIN_DIR = DRIVE_ROOT / "Garmin_Export"
APPLE_HEALTH_DIR = DRIVE_ROOT / "AppleHealth_Export"

# Счётчики
stats = {"copied": 0, "skipped": 0, "errors": 0}


def normalize_filename(original_name: str) -> str:
    """
    Преобразует имя файла в стандартный формат:
    {тип}_{дата}_{источник}_{детали}.{ext}
    
    Пример: blood_cmd_2025-08-10_general.pdf -> blood_2025-08-10_cmd_general.pdf
    """
    # Извлекаем расширение
    name, ext = os.path.splitext(original_name)
    ext = ext.lower()
    
    # Паттерн: type_source_date_details или type_date_source_details
    # Пробуем распознать формат
    
    # Формат 1: blood_cmd_2025-08-10_general
    pattern1 = r'^([a-z-]+)_([a-z]+)_(\d{4}-\d{2}-\d{2})_(.+)$'
    match = re.match(pattern1, name, re.IGNORECASE)
    if match:
        doc_type, source, date, details = match.groups()
        return f"{doc_type}_{date}_{source}_{details}{ext}"
    
    # Формат 2: medical-record_therapist_2021-03-01
    pattern2 = r'^([a-z-]+)_([a-z]+)_(\d{4}-\d{2}-\d{2})$'
    match = re.match(pattern2, name, re.IGNORECASE)
    if match:
        doc_type, source, date = match.groups()
        return f"{doc_type}_{date}_{source}{ext}"
    
    # Формат 3: genetics_tsmt_2009-04-02_polymorphism
    # Уже соответствует паттерну 1
    
    # Формат 4: ultrasound_urinary-system_2021-03-01 (без источника)
    pattern4 = r'^([a-z-]+)_([a-z-]+)_(\d{4}-\d{2}-\d{2})$'
    match = re.match(pattern4, name, re.IGNORECASE)
    if match:
        doc_type, details, date = match.groups()
        return f"{doc_type}_{date}_{details}{ext}"
    
    # Если не удалось распознать — оставляем как есть
    return original_name


def copy_file(src: Path, dst_dir: Path, new_name: str = None):
    """Копирует файл с опциональным переименованием."""
    try:
        if new_name:
            dst = dst_dir / new_name
        else:
            dst = dst_dir / src.name
        
        # Проверяем, не существует ли уже
        if dst.exists():
            print(f"  ⏭️  Пропуск (уже существует): {dst.name}")
            stats["skipped"] += 1
            return
        
        shutil.copy2(src, dst)
        print(f"  ✅ {src.name} -> {dst.name}")
        stats["copied"] += 1
    except Exception as e:
        print(f"  ❌ Ошибка копирования {src.name}: {e}")
        stats["errors"] += 1


def migrate_directory(src_dir: Path, dst_dir: Path, rename: bool = True):
    """Мигрирует все файлы из директории."""
    if not src_dir.exists():
        print(f"⚠️  Директория не существует: {src_dir}")
        return
    
    files = [f for f in src_dir.iterdir() if f.is_file() and not f.name.startswith('.')]
    print(f"\n📁 {src_dir.name}: {len(files)} файлов")
    
    for file in sorted(files):
        new_name = normalize_filename(file.name) if rename else file.name
        copy_file(file, dst_dir, new_name)


def migrate_garmin():
    """Мигрирует Garmin данные, сохраняя структуру подпапок."""
    garmin_src = SOURCE_DATA / "garmin"
    if not garmin_src.exists():
        return
    
    print(f"\n📁 Garmin: миграция подпапок...")
    
    subdirs = ["activities", "body-battery", "daily-summary", "hrv", "sleep", "stress"]
    
    for subdir in subdirs:
        src = garmin_src / subdir
        if not src.exists():
            continue
        
        dst = GARMIN_DIR / subdir
        dst.mkdir(parents=True, exist_ok=True)
        
        files = list(src.glob("*.json"))
        print(f"  📂 {subdir}: {len(files)} файлов")
        
        for file in files:
            copy_file(file, dst)


def migrate_apple_health():
    """Мигрирует Apple Health экспорты."""
    src_dir = SOURCE_DATA / "apple-health" / "export"
    if not src_dir.exists():
        return
    
    print(f"\n📁 Apple Health Export...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for file in src_dir.iterdir():
        if file.is_file() and file.suffix == ".xml":
            # Добавляем дату к имени
            new_name = f"{file.stem}_{today}.xml"
            copy_file(file, APPLE_HEALTH_DIR, new_name)


def main():
    print("=" * 60)
    print("🚀 Миграция данных на Google Drive")
    print("=" * 60)
    
    # Проверяем, что Drive примонтирован
    if not DRIVE_ROOT.exists():
        print(f"❌ Google Drive не найден: {DRIVE_ROOT}")
        return
    
    # === АЛЕКСАНДР ===
    print("\n👤 АЛЕКСАНДР")
    print("-" * 40)
    
    alexander_dirs = [
        "blood-tests",
        "medical-records",
        "covid-tests",
        "hormones",
        "genetics",
        "ultrasound",
        "urine-tests",
        "vitamins",
    ]
    
    for dir_name in alexander_dirs:
        migrate_directory(SOURCE_DATA / dir_name, ALEXANDER_DIR)
    
    # === ВАЛЕРИЯ ===
    print("\n👤 ВАЛЕРИЯ НИКОЛАЕВНА")
    print("-" * 40)
    migrate_directory(SOURCE_DATA / "Valeria_Nikolaevna", VALERIA_DIR)
    
    # === GARMIN ===
    print("\n⌚ GARMIN")
    print("-" * 40)
    migrate_garmin()
    
    # === APPLE HEALTH ===
    print("\n🍎 APPLE HEALTH")
    print("-" * 40)
    migrate_apple_health()
    
    # Итоги
    print("\n" + "=" * 60)
    print("📊 ИТОГИ МИГРАЦИИ")
    print("=" * 60)
    print(f"  ✅ Скопировано: {stats['copied']}")
    print(f"  ⏭️  Пропущено (уже есть): {stats['skipped']}")
    print(f"  ❌ Ошибок: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
