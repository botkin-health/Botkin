#!/usr/bin/env python3
"""
Helper script to batch update all remaining files to use config.get_settings()
"""

import sys
from pathlib import Path

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings

# Export for backward compatibility
def get_openai_api_key():
    """Get OpenAI API key from settings"""
    return get_settings().openai_api_key

def get_google_api_key():
    """Get Google API key from settings"""
    return get_settings().google_api_key

def get_garmin_credentials():
    """Get Garmin credentials from settings"""
    settings = get_settings()
    return settings.garmin_email, settings.garmin_password
