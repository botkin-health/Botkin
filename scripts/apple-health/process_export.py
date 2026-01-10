#!/usr/bin/env python3
"""
Скрипт для обработки экспорта Apple Health:
- Распаковывает ZIP из Downloads
- Перемещает XML в правильную папку с правильным именем
- Удаляет исходные файлы
"""
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

DOWNLOADS_DIR = Path("/Users/alexlyskovsky/Downloads")
EXPORT_DIR = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/export")

def find_export_zip():
    """Находит export.zip в Downloads"""
    zip_file = DOWNLOADS_DIR / "export.zip"
    if zip_file.exists():
        return zip_file
    return None

def extract_and_process():
    """Распаковывает и обрабатывает экспорт"""
    zip_file = find_export_zip()
    if not zip_file:
        print("❌ Файл export.zip не найден в Downloads")
        return False
    
    print(f"📦 Найден файл: {zip_file}")
    
    # Создаем временную папку для распаковки
    temp_dir = DOWNLOADS_DIR / "export_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    try:
        # Распаковываем
        print("📂 Распаковка архива...")
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Ищем XML файлы
        xml_files = list(temp_dir.rglob("*.xml"))
        print(f"📄 Найдено XML файлов: {len(xml_files)}")
        
        if not xml_files:
            print("❌ XML файлы не найдены в архиве")
            return False
        
        # Проверяем существующие файлы
        existing_files = list(EXPORT_DIR.glob("*.xml"))
        print(f"📋 Существующие файлы в export/: {[f.name for f in existing_files]}")
        
        # Обрабатываем каждый XML файл
        for xml_file in xml_files:
            # Определяем имя файла
            if "export.xml" in xml_file.name or xml_file.name == "export.xml":
                new_name = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            else:
                new_name = f"{xml_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            
            dest_file = EXPORT_DIR / new_name
            
            # Проверяем на дубликаты (по размеру и первым строкам)
            if dest_file.exists():
                print(f"⚠️  Файл {new_name} уже существует, пропускаем")
                continue
            
            # Перемещаем файл
            print(f"📤 Перемещение {xml_file.name} → {new_name}")
            shutil.move(str(xml_file), str(dest_file))
            print(f"✅ Файл сохранен: {dest_file}")
        
        # Удаляем временную папку
        print("🧹 Удаление временных файлов...")
        shutil.rmtree(temp_dir)
        
        # Удаляем ZIP файл
        print(f"🗑️  Удаление {zip_file.name}...")
        zip_file.unlink()
        
        print("✅ Обработка завершена!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        return False

if __name__ == "__main__":
    extract_and_process()
