import os
import logging
from pathlib import Path
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class VoiceService:
    def __init__(self):
        self.api_key = self._get_api_key()
        if not self.api_key:
            logger.error("❌ OPENAI_API_KEY не найден в переменных окружения или файлах!")
        else:
            self.client = AsyncOpenAI(api_key=self.api_key)

    def _get_api_key(self):
        key = os.getenv("OPENAI_API_KEY")
        if key and key.strip() and key != "your_openai_key_here":
            return key.strip()
        return None

    async def transcribe(self, file_path: Path) -> str:
        """
        Транскрибирует аудиофайл в текст с помощью OpenAI Whisper.
        """
        try:
            if not file_path.exists():
                raise FileNotFoundError(f"Файл не найден: {file_path}")

            logger.info(f"🎤 Отправляю файл в Whisper: {file_path}")
            
            with open(file_path, "rb") as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file,
                    response_format="text"
                )
            
            logger.info(f"✅ Успешно транскрибировано: {transcript[:50]}...")
            return transcript

        except Exception as e:
            logger.error(f"❌ Ошибка при транскрибации: {e}")
            raise

# Создаем глобальный экземпляр
voice_service = VoiceService()
