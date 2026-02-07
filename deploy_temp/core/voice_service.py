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
        # 1. Env var
        key = os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_key_here":
            return key
            
        # 2. Project Root File (.openai_api_key)
        try:
            # services/voice_service.py -> telegram-bot/services/ -> telegram-bot/ -> HealthVault/
            root_key = Path(__file__).parent.parent / ".openai_api_key"
            if root_key.exists():
                return root_key.read_text().strip()
        except Exception as e:
            logger.error(f"Error reading root key: {e}")

        # 3. FamilyDocs
        try:
            key_path = Path(os.path.expanduser("~/FamilyDocs/.openai_api_key"))
            if key_path.exists():
                return key_path.read_text().strip()
        except Exception as e:
            logger.error(f"Error reading key from file: {e}")
            
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
