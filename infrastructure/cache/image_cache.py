#!/usr/bin/env python3
"""
Image Cache - хеш-based кэширование результатов Vision API

Цель: Избегать повторных вызовов дорогих Vision API для одних и тех же изображений.

Механика:
1. Считаем SHA256 от файла изображения
2. Проверяем в кэше: если есть - возвращаем результат
3. Если нет - вызываем API и сохраняем результат в кэш
4. TTL = 7 дней (configurable)
"""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta

# Add project root
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings


class ImageCache:
    """
    SQLite-based cache for vision API results.
    Key = SHA256(image), Value = JSON result
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        settings = get_settings()
        
        if db_path is None:
            cache_dir = settings.data_dir / "cache"
            cache_dir.mkdir(exist_ok=True)
            db_path = cache_dir / "image_cache.db"
        
        self.db_path = db_path
        self.ttl_days = settings.cache_ttl_days
        self._init_db()
    
    def _init_db(self):
        """Создает таблицу если не существует"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS image_cache (
                    image_hash TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            # Индекс для быстрой очистки expired
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at 
                ON image_cache(expires_at)
            """)
            conn.commit()
    
    def _compute_hash(self, image_path: Path) -> str:
        """Считает SHA256 от файла"""
        sha256 = hashlib.sha256()
        with open(image_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def get(self, image_path: Path) -> Optional[Dict]:
        """
        Получает закэшированный результат.
        
        Returns:
            Dict с результатом или None если не найдено/expired
        """
        if not image_path.exists():
            return None
        
        image_hash = self._compute_hash(image_path)
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT result_json FROM image_cache
                WHERE image_hash = ? AND expires_at > ?
            """, (image_hash, now))
            
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        
        return None
    
    def set(self, image_path: Path, result: Dict):
        """
        Сохраняет результат в кэш.
        
        Args:
            image_path: Путь к изображению
            result: Результат от Vision API (dict)
        """
        if not image_path.exists():
            return
        
        image_hash = self._compute_hash(image_path)
        now = datetime.now()
        expires_at = now + timedelta(days=self.ttl_days)
        
        result_json = json.dumps(result, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO image_cache 
                (image_hash, result_json, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (image_hash, result_json, now.isoformat(), expires_at.isoformat()))
            conn.commit()
    
    def cleanup(self):
        """Удаляет expired записи"""
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM image_cache WHERE expires_at < ?
            """, (now,))
            deleted = cursor.rowcount
            conn.commit()
        
        return deleted
    
    def clear(self):
        """Очищает весь кэш"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM image_cache")
            conn.commit()
    
    def stats(self) -> Dict:
        """Статистика кэша"""
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM image_cache")
            total = cursor.fetchone()[0]
            
            cursor = conn.execute("""
                SELECT COUNT(*) FROM image_cache WHERE expires_at > ?
            """, (now,))
            valid = cursor.fetchone()[0]
            
            expired = total - valid
        
        return {
            "total": total,
            "valid": valid,
            "expired": expired
        }


# Singleton instance
_cache_instance: Optional[ImageCache] = None

def get_image_cache() -> ImageCache:
    """Получает singleton instance кэша"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ImageCache()
    return _cache_instance


if __name__ == "__main__":
    # Test
    cache = ImageCache()
    print(f"Cache stats: {cache.stats()}")
    
    # Cleanup
    deleted = cache.cleanup()
    print(f"Deleted {deleted} expired entries")
