"""Shared helpers for agent_tools domain routers.

Timezone/date conversion and KB-file-path resolution used across multiple
domains (nutrition, glucose, dashboard, kb, biomarkers, reports, profile).
Extracted from the former monolithic agent_tools_api.py (split 2026-09-06).

NOTE: this file is one directory deeper than agent_tools_api.py was, so
_resolve_user_kb_path uses parents[3] (not [2]) to reach the repo root.
tests/test_agent_tools_common.py pins that.
"""

import logging
import re
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


_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_agent_datetime(raw: Optional[str], user) -> datetime:
    """Parse an ISO datetime string from an agent write-tool request.

    A NAIVE value (no offset/'Z') is localized in the USER's own timezone —
    NEVER treated as UTC. #518: agents almost always send a naive string
    ("2026-09-21T23:00:00") because the tool's own prompt only asks them to
    "figure out the date", not the timezone. If that naive value is stored
    as-is in a `timestamptz` column, Postgres/`_dt_to_user_tz()` both assume
    UTC — for a Europe/Moscow (+3) user, a 23:00 evening reading rolls onto
    the next calendar day. Same class of bug as #500/#502
    (`workouts._parse_manual_start_time`, which this shares logic with).

    A string that already carries an explicit offset (or 'Z') is respected
    as-is — the agent computed it itself, we don't second-guess it.
    """
    tz = _get_user_tz(user)
    if not raw:
        return datetime.now(tz)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {raw!r}. Use ISO datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def parse_agent_date_or_datetime(raw: Optional[str], user) -> datetime:
    """Like :func:`parse_agent_datetime`, but a DATE-ONLY value ("YYYY-MM-DD",
    no time component) is combined with the CURRENT time-of-day in the user's
    timezone instead of collapsing to midnight.

    #518: a bare date used to become `datetime(y, m, d, 0, 0, 0)`, localized
    (or — before this fix — misread as UTC midnight). Two different same-day
    readings sent with only a date ("утром 130/85", "вечером 140/90") both
    landed on that same midnight value, and `ON CONFLICT (user_id,
    measured_at) DO UPDATE` silently overwrote the first with the second —
    real data quietly lost. Combining the date with wall-clock "now" (down to
    microseconds) makes distinct calls land on distinct timestamps, so they
    no longer collide. A genuine retry of the exact same reading is expected
    to carry an explicit time (not just a date) and dedupes via
    :func:`parse_agent_datetime` instead.
    """
    if raw and _DATE_ONLY_RE.match(raw.strip()):
        tz = _get_user_tz(user)
        now_local = datetime.now(tz)
        year, month, day = (int(part) for part in raw.strip().split("-"))
        return datetime(
            year,
            month,
            day,
            now_local.hour,
            now_local.minute,
            now_local.second,
            now_local.microsecond,
            tzinfo=tz,
        )
    return parse_agent_datetime(raw, user)


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
    Пишущим вызовам вместо этого нужен :func:`_ensure_user_kb_path`.
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


def _ensure_user_kb_path(user, project_root: Optional[Path] = None) -> tuple[Path, str]:
    """То же, что :func:`_resolve_user_kb_path`, но для ПИШУЩИХ вызовов.

    Если KB-файла ещё нет — создаёт пустой по текущему layout'у
    (``data/kb/kb_<telegram_id>.json``) и возвращает его.

    Зачем (фикс 22.09.2026): KB-файлы заводит только
    ``scripts/sync_family_kb.py`` для family-юзеров. У early_user/external его
    нет никогда, поэтому ``add_agent_correction`` падал с 404 «KB не найден» —
    то есть агент физически не мог запомнить ничего о таком пациенте. Одному из
    early-юзеров агент так и написал: «техническая заметка не сохранилась в
    базу», потеряв его наблюдение о связи веса и алкоголя с хронической тазовой
    болью; у второго ошибка повторилась. Разбор — в отчёте ночной смены
    22.09.2026, F-001.

    Каталог ``data/`` уже примонтирован в контейнер (``./data:/app/data``),
    поэтому созданный файл переживает рестарт, но НЕ переживает потерю тома —
    долгосрочно корректировки стоит перенести в Postgres (см. P-003 в отчёте
    ночной смены 22.09.2026).

    ``project_root`` переопределяется только в тестах.
    """
    path, source = _resolve_user_kb_path(user)
    if path is not None:
        return path, source

    root = project_root or Path(__file__).resolve().parents[3]
    new_path = root / "data" / "kb" / f"kb_{user.telegram_id}.json"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text("{}", encoding="utf-8")
    logger.info("Created empty KB for user %s at %s", user.telegram_id, new_path)
    return new_path, f"data/kb/kb_{user.telegram_id}.json"
