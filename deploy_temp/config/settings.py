#!/usr/bin/env python3
"""
Unified configuration for HealthVault.
All secrets and settings should come from environment variables.
"""
from pathlib import Path
from typing import Optional
from functools import lru_cache
import os


class Settings:
    """
    Application settings loaded from environment variables.
    
    Usage:
        from config import get_settings
        settings = get_settings()
        bot = Bot(token=settings.telegram_bot_token)
    """
    
    def __init__(self):
        # Load environment variables from .env file
        from dotenv import load_dotenv
        load_dotenv()  # Load from .env in current directory
        load_dotenv(Path(__file__).parent.parent / '.env')  # Load from project root
        
        # Project paths
        self.project_root = Path(__file__).parent.parent
        self.data_dir = self.project_root / "data"
        
        # Telegram Bot
        self.telegram_bot_token: str = self._get_required("TELEGRAM_BOT_TOKEN")
        
        # AI Services
        self.openai_api_key: Optional[str] = self._get_optional("OPENAI_API_KEY")
        self.google_api_key: Optional[str] = self._get_optional("GOOGLE_API_KEY")
        self.gemini_api_key: Optional[str] = self._get_optional("GEMINI_API_KEY")
        
        # Garmin (optional for sync)
        self.garmin_email: Optional[str] = self._get_optional("GARMIN_EMAIL")
        self.garmin_password: Optional[str] = self._get_optional("GARMIN_PASSWORD")
        
        # Feature flags
        self.enable_vision: bool = self._get_bool("ENABLE_VISION", default=True)
        self.enable_voice: bool = self._get_bool("ENABLE_VOICE", default=True)
        
        # Cache settings
        self.cache_enabled: bool = self._get_bool("CACHE_ENABLED", default=True)
        self.cache_ttl_days: int = int(self._get_optional("CACHE_TTL_DAYS") or "7")
        
        # Logging
        self.log_level: str = self._get_optional("LOG_LEVEL") or "INFO"
        
    def _get_required(self, key: str) -> str:
        """Get required environment variable or raise error"""
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"Требуется переменная окружения: {key}\n"
                f"Создайте файл .env или установите переменную."
            )
        return value
    
    def _get_optional(self, key: str) -> Optional[str]:
        """Get optional environment variable"""
        return os.getenv(key)
    
    def _get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean environment variable"""
        value = os.getenv(key)
        if value is None:
            return default
        return value.lower() in ('true', '1', 'yes', 'on')
    
    @property
    def has_openai(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(self.openai_api_key)
    
    @property
    def has_google_vision(self) -> bool:
        """Check if Google Vision API key is configured"""
        return bool(self.google_api_key)
    
    @property
    def has_gemini(self) -> bool:
        """Check if Gemini API key is configured"""
        return bool(self.gemini_api_key)


@lru_cache()
def get_settings() -> Settings:
    """
    Get settings singleton.
    Cached to avoid re-reading environment on every call.
    """
    return Settings()


# Backward compatibility: allow importing directly
__all__ = ['Settings', 'get_settings']
