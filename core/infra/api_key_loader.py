#!/usr/bin/env python3
"""
Unified API key loader for backward compatibility.
New code should use config.get_settings() directly.
"""

import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings


def load_google_vision_api_key() -> Optional[str]:
    """
    Load Google Vision API key from settings.

    Returns:
        API key or None if not configured
    """
    settings = get_settings()
    return settings.google_api_key


def get_google_vision_api_key(provided_key: Optional[str] = None) -> Optional[str]:
    """
    Get API key, using provided key or loading from settings.

    Args:
        provided_key: Explicitly provided key (has priority)

    Returns:
        API key or None
    """
    # If key is explicitly provided - use it
    if provided_key and provided_key.strip() and provided_key != "your_google_vision_key_here":
        api_key = provided_key.strip()
        if len(api_key) > 20:
            return api_key

    # Otherwise load from settings
    return load_google_vision_api_key()
