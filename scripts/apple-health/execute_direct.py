import zipfile
import shutil
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

DOWNLOADS_DIR = Path("/Users/alexlyskovsky/Downloads")
EXPORT_DIR = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/export")
WEIGHTS_FILE = Path("/Users/alexlyskovsky/HealthVault/data/weights/apple_health_weights.json")

# Распаковываем
zip_file = DOWNLOADS_DIR / "export.zip"
if not zip_file.exists():
    print("❌ Файл export.zip не найден")
    exit(1)

print(f"📦 Найден файл: {zip_file}")
temp_dir = DOWNLOADS_DIR / "export_temp"
if temp_dir.exists():
    shutil.rmtree(temp_dir)
temp_dir.mkdir()

print("📂 Распаковка...")
with zipfile.ZipFile(zip_file, 'r') as zip_ref:
    zip_ref.extractall(temp_dir)

xml_files = list(temp_dir.rglob("*.xml"))
print(f"📄 Найдено XML: {len(xml_files)}")

# Перемещаем
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
moved_files = []
for xml_file in xml_files:
    new_name = f"export_{timestamp}.xml"
    dest_file = EXPORT_DIR / new_name
    if not dest_file.exists():
        shutil.move(str(xml_file), str(dest_file))
        moved_files.append(dest_file)
        print(f"✅ Сохранен: {new_name}")

# Извлекаем вес
all_weights = []
for xml_file in moved_files:
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for record in root.findall('.//Record'):
            if record.get('type') == 'HKQuantityTypeIdentifierBodyMass':
                all_weights.append({
                    'value': float(record.get('value', 0)),
                    'sourceName': record.get('sourceName', ''),
                    'startDate': record.get('startDate', '')
                })
    except Exception as e:
        print(f"⚠️  Ошибка при парсинге {xml_file.name}: {e}")

print(f"📊 Найдено записей о весе: {len(all_weights)}")

# Обновляем JSON
if WEIGHTS_FILE.exists():
    with open(WEIGHTS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    existing_dates = {e['date'] for e in data.get('entries', [])}
else:
    data = {"source": "apple_health", "export_date": datetime.now().isoformat(), "total_days": 0, "entries": []}
    existing_dates = set()

new_count = 0
for w in all_weights:
    try:
        date_str = w['startDate'].split(' +')[0]
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        date = dt.date().isoformat()
        if date not in existing_dates:
            data['entries'].append({
                "date": date,
                "weight_kg": w['value'],
                "time": w['startDate'],
                "source": w['sourceName']
            })
            existing_dates.add(date)
            new_count += 1
    except Exception as e:
        pass

data['entries'] = sorted(data['entries'], key=lambda x: x['date'], reverse=True)
data['export_date'] = datetime.now().isoformat()
data['total_days'] = len(data['entries'])

with open(WEIGHTS_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ Добавлено новых записей: {new_count}")

# Сравнение
print("\n" + "="*60)
print("📊 СРАВНЕНИЕ С УМНЫМИ ВЕСАМИ")
print("="*60)
print(f"\n🎯 Умные весы (Zepp Life):")
print(f"   Вес: 81.90 кг")
print(f"   Дата: 2026-01-08")
print(f"   Время: 13:16")

entry_2026_01_08 = next((e for e in data['entries'] if e['date'] == '2026-01-08'), None)
if entry_2026_01_08:
    print(f"\n📱 Apple Health:")
    print(f"   Вес: {entry_2026_01_08['weight_kg']} кг")
    print(f"   Дата: {entry_2026_01_08['date']}")
    print(f"   Время: {entry_2026_01_08.get('time', 'N/A')}")
    print(f"   Источник: {entry_2026_01_08.get('source', 'N/A')}")
    diff = abs(entry_2026_01_08['weight_kg'] - 81.90)
    if diff < 0.1:
        print(f"\n✅ Данные совпадают (разница: {diff:.3f} кг)")
        print("✅ ВЫВОД: Все данные переносятся автоматически из Apple Health")
        print("✅ Скриншоты из умных весов НЕ НУЖНЫ - данные синхронизируются")
    else:
        print(f"\n⚠️  Разница: {diff:.3f} кг")
        print("⚠️  Возможно, нужно проверить синхронизацию")
else:
    print("\n❌ Запись за 2026-01-08 не найдена в Apple Health")
    print("⚠️  ВЫВОД: Возможно, нужно подгрузить скриншот из умных весов")
    print("⚠️  Или данные еще не синхронизировались с Apple Health")

# Показываем последние записи
print(f"\n📋 Последние 5 записей из Apple Health:")
for entry in data['entries'][:5]:
    print(f"   {entry['date']}: {entry['weight_kg']} кг ({entry.get('source', 'N/A')})")

# Удаляем временные файлы
print("\n🧹 Удаление временных файлов...")
if temp_dir.exists():
    shutil.rmtree(temp_dir)
    print("✅ Временная папка удалена")

# Удаляем ZIP файл
if zip_file.exists():
    try:
        zip_file.unlink()
        print(f"✅ {zip_file.name} удален из Downloads")
    except Exception as e:
        print(f"⚠️  Не удалось удалить {zip_file.name}: {e}")
        print(f"   Попробуйте удалить вручную: {zip_file}")

print("\n✅ Обработка завершена!")
