"""Единая таймзона проекта.

MSK — фиксированный UTC+3, используется как fallback.
get_user_tz(user_id) — per-user ZoneInfo из users.timezone (корректно
обрабатывает DST, например Asia/Jerusalem UTC+2/+3).
"""

from datetime import timedelta, timezone

MSK = timezone(timedelta(hours=3))

_DEFAULT_TZ_NAME = "Europe/Moscow"


def get_user_tz(user_id: int):
    """Return ZoneInfo for user's timezone. Falls back to Europe/Moscow.

    Lazy imports inside the function avoid circular-import issues since
    core.infra.tz is loaded early by many modules.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        from database import SessionLocal
        from database.crud import get_user_by_telegram_id

        db = SessionLocal()
        try:
            user = get_user_by_telegram_id(db, user_id)
            tz_name = (getattr(user, "timezone", None) if user else None) or _DEFAULT_TZ_NAME
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            return ZoneInfo(_DEFAULT_TZ_NAME)
        finally:
            db.close()
    except Exception:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_DEFAULT_TZ_NAME)
