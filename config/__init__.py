"""
Configuration module for HealthVault.
Provides unified access to all settings and secrets.
"""

from .settings import get_settings, Settings

__all__ = ["get_settings", "Settings"]
