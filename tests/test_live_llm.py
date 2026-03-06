#!/usr/bin/env python3
import sys
import os
import json
import logging
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_router import analyze_message

logging.basicConfig(level=logging.INFO)

def test_multiple_dishes_photo():
    """Тест: LLM Router должен распознать несколько блюд на разных фото раздельно."""
    print("🚀 Запускаем Live-Test LLM Router (GPT-4o) с тестовыми фотографиями...")
    
    # Пути к тестовым фото салата и лосося
    base_dir = Path("/Users/alexlyskovsky/.gemini/antigravity/brain/96018094-5394-4027-a8c6-665750d458f0")
    images = [
        base_dir / "media__1772380978042.jpg",
        base_dir / "media__1772380980503.jpg"
    ]
    
    # Проверяем наличие файлов
    valid_images = [str(p) for p in images if p.exists()]
    if len(valid_images) < 2:
        print("❌ Тестовые изображения не найдены локально. Тест пропущен.")
        return
        
    result = analyze_message(text="", image_paths=valid_images)
    
    if not result or result.get("type") != "food":
        print("❌ Ошибка: Роутер вернул пустой результат или не 'food'")
        sys.exit(1)
        
    items = result.get("data", {}).get("items", [])
    
    print(f"\n✅ Получено {len(items)} элементов:")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item.get('name')} - {item.get('weight')}г")
        
    assert len(items) >= 2, f"❌ Провал: Ожидалось минимум 2 раздельных блюда, получено {len(items)}"
    
    # Check that we have both fish/salmon and salad/shrimp
    names = [i.get('name', '').lower() for i in items]
    has_fish = any('лосось' in n or 'рыб' in n for n in names)
    has_salad = any('салат' in n for n in names)
    has_broccoli = any('брокколи' in n for n in names)
    
    assert has_fish and (has_salad or has_broccoli), "❌ Провал: Нейросеть пропустила салат или рыбу"
    
    total_weight = sum(i.get('weight', 0) or 0 for i in items)
    assert total_weight > 200, f"❌ Провал: Суммарный вес слишком мал ({total_weight}г), возможно блюда склеены"
    
    print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Промпт работает отлично.")

if __name__ == "__main__":
    test_multiple_dishes_photo()
