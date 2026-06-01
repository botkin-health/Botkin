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


# ---------------------------------------------------------------------------
# KB user mapping — единый маппинг telegram_id → имя папки FamilyHealth.
# Раньше дублировался в scripts/sync_family_kb.py (USERS) и в ad-hoc скриптах.
# ---------------------------------------------------------------------------

KB_USERS: dict[int, str] = {
    895655: "Александр Лысковский — Здоровье",
    REDACTED_ID: "Павел REDACTED — Здоровье",
    REDACTED_ID: "Игорь Лысковский — Здоровье",
    REDACTED_ID: "Андрей REDACTED — Здоровье",
    REDACTED_ID: "Олег Лысковский — Здоровье",
    REDACTED_ID: "Валерия Лысковская — Здоровье",
    REDACTED_ID: "Дмитрий REDACTED — Здоровье",
}
