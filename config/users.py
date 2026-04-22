"""
User configuration for HealthVault bot.

Open registration: any Telegram user can sign up.
Authorization is handled via users.is_active in the database (AuthMiddleware).
"""

# Admin Telegram ID — can use /block, /unblock, /users commands
ADMIN_USER_ID = 895655  # Alex Lyskovsky


def is_admin(telegram_id: int) -> bool:
    """Check if user has admin privileges."""
    return telegram_id == ADMIN_USER_ID
