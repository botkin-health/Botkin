"""
User authorization configuration for HealthVault bot.

This module contains the whitelist of allowed Telegram users
and authorization logic.
"""

# Whitelist of allowed Telegram IDs
ALLOWED_USERS = {
    895655,  # Alex Lyskovsky
    485132,  # Nika Selezneva
    836757955,  # Andrey
}


def is_user_allowed(telegram_id: int) -> bool:
    """
    Check if user is authorized to use the bot.

    Args:
        telegram_id: Telegram user ID

    Returns:
        True if user is in whitelist, False otherwise
    """
    return telegram_id in ALLOWED_USERS


def get_allowed_users_count() -> int:
    """Get number of allowed users"""
    return len(ALLOWED_USERS)
