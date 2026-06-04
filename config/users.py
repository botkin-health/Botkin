"""
User configuration for Botkin bot.

Open registration: any Telegram user can sign up.
Authorization is handled via users.is_active in the database (AuthMiddleware).

Admin ID и маппинг telegram_id → ФИО (PII) НЕ хранятся в публичном репо:
- ADMIN_USER_ID — из env BOTKIN_ADMIN_ID
- KB_USERS — из приватного config/users_private.py (в .gitignore), fallback {}.
"""

import os

# Admin Telegram ID — из env (раньше был захардкожен с именем). Команды /block, /unblock, /users.
ADMIN_USER_ID = int(os.getenv("BOTKIN_ADMIN_ID", "0") or "0")


def is_admin(telegram_id: int) -> bool:
    """Check if user has admin privileges."""
    return ADMIN_USER_ID != 0 and telegram_id == ADMIN_USER_ID


# ---------------------------------------------------------------------------
# KB user mapping — единый маппинг telegram_id → имя папки FamilyHealth.
# Реальные ФИО — PII, вынесены в приватный config/users_private.py (.gitignore).
# В публичном репо / чистом клоне маппинг пустой.
# ---------------------------------------------------------------------------

try:
    from config.users_private import KB_USERS
except ImportError:
    KB_USERS: dict[int, str] = {}
