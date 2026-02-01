import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add HealthVault root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

# Load .env (assuming it is in telegram-bot or root)
load_dotenv(Path(__file__).parent.parent / "telegram-bot" / ".env")

from core.voice_service import voice_service
from core.nutrition import process_meal_description

async def main():
    file_path = Path("/Users/alexlyskovsky/Downloads/2026-01-11 13.37.04.ogg")
    print(f"🎤 1. Читаю файл: {file_path}")
    
    if not file_path.exists():
        print("❌ Файл не найден!")
        return

    # 1. Transcribe
    try:
        text = await voice_service.transcribe(file_path)
        print(f"📝 2. Распознанный текст: '{text}'")
    except Exception as e:
        print(f"❌ Ошибка транскрибации: {e}")
        return

    # 2. Analyze Nutrition
    print(f"🤖 3. Анализирую питание через ChatGPT...")
    try:
        # process_meal_description is synchronous
        meal_items, meal_totals = process_meal_description(description=text)
        
        print("\n📊 4. Результат анализа:")
        print("-" * 40)
        for item in meal_items:
            print(f"   • {item['product']} ({item['weight_g']}г): {item['calories']} ккал")
        
        print("-" * 40)
        print(f"   Итого: {meal_totals['calories']} ккал | Б: {meal_totals['protein']} | Ж: {meal_totals['fats']} | У: {meal_totals['carbs']}")
        print("\n✅ УСПЕХ: Цепочка [Голос -> Текст -> КБЖУ] работает корректно.")
        
    except Exception as e:
        print(f"❌ Ошибка анализа питания: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
