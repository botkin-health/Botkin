"""Shared helpers for agent_tools domain routers.

Timezone/date conversion and KB-file-path resolution used across multiple
domains (nutrition, glucose, dashboard, kb, biomarkers, reports, profile).
Extracted from the former monolithic agent_tools_api.py (split 2026-09-06).

NOTE: this file is one directory deeper than agent_tools_api.py was, so
_resolve_user_kb_path uses parents[3] (not [2]) to reach the repo root.
tests/test_agent_tools_common.py pins that.
"""

import logging
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

logger = logging.getLogger(__name__)


_DEFAULT_TZ = "Europe/Moscow"


def _get_user_tz(user) -> ZoneInfo:
    """Return ZoneInfo timezone for user. Falls back to Europe/Moscow."""
    tz_name = getattr(user, "timezone", None) or _DEFAULT_TZ
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "Unknown timezone %r for user %s, falling back to %s",
            tz_name,
            getattr(user, "telegram_id", "?"),
            _DEFAULT_TZ,
        )
        return ZoneInfo(_DEFAULT_TZ)


def _dt_to_user_tz(dt: datetime, user) -> datetime:
    """Convert a UTC (or timezone-aware) datetime to the user's local timezone."""
    if dt is None:
        return dt
    tz = _get_user_tz(user)
    # Ensure dt is timezone-aware (treat naive as UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def _dt_isoformat_local(dt: datetime, user) -> Optional[str]:
    """Convert UTC datetime to user's timezone and return ISO string (no microseconds)."""
    if dt is None:
        return None
    local_dt = _dt_to_user_tz(dt, user)
    # Format without microseconds for readability: 2026-05-27T21:18:00+03:00
    return local_dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _today_in_user_tz(user) -> date:
    """Return today's date in the user's local timezone."""
    tz = _get_user_tz(user)
    return datetime.now(tz).date()


def _parse_date(date_str: Optional[str], user=None) -> date:
    """Parse YYYY-MM-DD string or return today in user's local timezone."""
    if not date_str:
        return _today_in_user_tz(user) if user is not None else date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str!r}. Use YYYY-MM-DD.")


def _as_dict(values):
    """blood_tests.values: dict в Postgres (JSONB), но str если пришло как JSON-текст."""
    if isinstance(values, str):
        import json as _json

        try:
            return _json.loads(values)
        except Exception:
            return {}
    return values or {}


def _resolve_user_kb_path(user) -> tuple[Optional[Path], str]:
    """Resolve per-user KB file path with fallback to legacy locations.

    Search order (first hit wins):
      1. ``data/kb/kb_<telegram_id>.json`` — current layout (since 2026-05-24
         refactor). Auto-mounted into the bot container via the existing
         ``./data:/app/data`` bind-mount in docker-compose.prod.yml.
      2. ``kb_<telegram_id>.json`` at repo root — legacy layout, kept for
         backward-compat during the rolling migration. Required per-file
         bind-mounts in docker-compose.prod.yml (now removed).
      3. ``knowledge_base.json`` at repo root — owner-cohort fallback (Alex).

    Returns ``(path, source_label)``. Path is None when no KB available;
    caller should return ``"kb-not-available"`` sentinel to the agent.
    """
    project_root = Path(__file__).resolve().parents[3]  # one level deeper than the old agent_tools_api.py
    new_path = project_root / "data" / "kb" / f"kb_{user.telegram_id}.json"
    legacy_path = project_root / f"kb_{user.telegram_id}.json"

    if new_path.exists():
        return new_path, f"data/kb/kb_{user.telegram_id}.json"
    if legacy_path.exists():
        return legacy_path, f"kb_{user.telegram_id}.json"
    if user.cohort == "owner":
        owner_kb = project_root / "knowledge_base.json"
        if owner_kb.exists():
            return owner_kb, "knowledge_base.json"
    return None, "kb-not-available"
