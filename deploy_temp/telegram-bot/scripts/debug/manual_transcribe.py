import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add current dir to sys.path
sys.path.append(str(Path(__file__).parent))

# Load env for API key
load_dotenv()

from services.voice_service import voice_service

async def main():
    file_path = Path("/Users/alexlyskovsky/Downloads/2026-01-11 13.37.04.ogg")
    
    print(f"🎤 Читаю файл: {file_path}")
    if not file_path.exists():
        print("❌ Файл не найден!")
        return

    try:
        text = await voice_service.transcribe(file_path)
        print("\n📝 РЕЗУЛЬТАТ:")
        print("-" * 20)
        print(text)
        print("-" * 20)
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())
