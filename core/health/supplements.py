"""
Supplement Service - PostgreSQL Version

Управление добавками и витаминами через PostgreSQL
"""

import html
import logging
from datetime import datetime
from typing import List, Dict, Optional

from core.infra.tz import get_user_tz  # noqa: E402

from database import SessionLocal, get_supplements_by_date, create_supplement_log
from database.crud import create_nutrition_log

logger = logging.getLogger(__name__)

# Supplements that also have nutritional value → auto-logged to nutrition_log
# Keyed by canonical lowercase name. Values are per one serving.
SUPPLEMENT_NUTRITION = {
    # Plan dose = 2 ч.л. ≈ 10 г порошка psyllium husk.
    "псиллиум": {
        "display": "Псиллиум (БАД)",
        "weight_g": 10,
        "calories": 36,
        "protein": 0.0,
        "fats": 0.0,
        "carbs": 10.0,
        "fiber": 8.0,
    },
    # Bombbar PRO whey: 1 порция = 30 г = 2 мерные ложки. Per 30 g по этикетке.
    "whey": {
        "display": "Whey (БАД)",
        "weight_g": 30,
        "calories": 107,
        "protein": 20.4,
        "fats": 5.5,
        "carbs": 2.0,
        "fiber": 0.0,
    },
}

# Synonyms → canonical lowercase key. Used both for SUPPLEMENT_NUTRITION lookup
# and for matching planned vs. logged names (voice ASR often drops doubled
# letters: «Псилиум» вместо «Псиллиум», «Омега-3» vs «Омега 3» и т.п.).
_NAME_SYNONYMS = {
    "псиллиум": "псиллиум",
    "псилиум": "псиллиум",
    "psyllium": "псиллиум",
    "омега 3": "омега 3",
    "омега-3": "омега 3",
    "омега3": "омега 3",
    "витамин d3": "витамин d3",
    "витамин д3": "витамин d3",
    "vitamin d3": "витамин d3",
    "d3": "витамин d3",
    "магний": "магний",
    "magnesium": "магний",
    "креатин": "креатин",
    "creatine": "креатин",
    "метилфолат": "метилфолат",
    "methylfolate": "метилфолат",
    "plant sterols": "plant sterols",
    "фитостеролы": "plant sterols",
    "k2": "k2 mk 7",
    "k2 mk 7": "k2 mk 7",
    "k2 mk7": "k2 mk 7",
    "витамин k2": "k2 mk 7",
    "mk 7": "k2 mk 7",
    "mk7": "k2 mk 7",
    "whey": "whey",
    "сывороточный протеин": "whey",
    "протеин": "whey",
}


def normalize_supplement_name(raw: str) -> str:
    """Return canonical lowercase key for matching, falling back to lower/strip."""
    key = (raw or "").strip().lower()
    # Collapse hyphens to spaces for synonym lookup, then exact lookup.
    normalized = key.replace("-", " ")
    normalized = " ".join(normalized.split())
    return _NAME_SYNONYMS.get(normalized, normalized)


def _canonical_supplement_name(raw: str) -> Optional[str]:
    key = normalize_supplement_name(raw)
    return key if key in SUPPLEMENT_NUTRITION else None


# Display names of all supplements that auto-mirror to nutrition_log.
# Used by the food editor to detect "this meal is a supplement mirror" and
# delete the parent supplements_log entry too.
SUPPLEMENT_DISPLAY_NAMES = {v["display"] for v in SUPPLEMENT_NUTRITION.values()}


def supplement_canonical_from_display(meal_name: str) -> Optional[str]:
    """Reverse lookup: given a nutrition_log.meal_name like 'Whey (БАД)',
    return the canonical supplement key ('whey'). None if not a mirror."""
    if not meal_name:
        return None
    target = meal_name.strip()
    for canon, info in SUPPLEMENT_NUTRITION.items():
        if info["display"] == target:
            return canon
    return None


def mirror_supplement_to_nutrition(db, user_id: int, target_date, current_time, supplement_name: str) -> None:
    """If `supplement_name` matches a known nutritional supplement, create a
    paired nutrition_log entry with the SAME `current_time`, so the food
    editor and supplements panel can find each other by (date, time, name)."""
    canonical = _canonical_supplement_name(supplement_name)
    nutri = SUPPLEMENT_NUTRITION.get(canonical) if canonical else None
    if not nutri:
        return
    food_item = {
        "name": nutri["display"],
        "weight_g": nutri["weight_g"],
        "calories": nutri["calories"],
        "protein": nutri["protein"],
        "fats": nutri["fats"],
        "carbs": nutri["carbs"],
        "fiber": nutri["fiber"],
    }
    totals = {
        "calories": nutri["calories"],
        "protein": nutri["protein"],
        "fats": nutri["fats"],
        "carbs": nutri["carbs"],
        "fiber": nutri["fiber"],
    }
    create_nutrition_log(
        db,
        user_id=user_id,
        date=target_date,
        meal_time=current_time,
        meal_name=nutri["display"],
        items=[food_item],
        totals=totals,
    )


def delete_mirror_nutrition_for(db, user_id: int, target_date, supplement_time, supplement_name: str) -> None:
    """Inverse of `mirror_supplement_to_nutrition`: remove the paired
    nutrition_log entry (matched by date + meal_time + display name)."""
    from database.models import NutritionLog

    canonical = _canonical_supplement_name(supplement_name)
    nutri = SUPPLEMENT_NUTRITION.get(canonical) if canonical else None
    if not nutri or supplement_time is None:
        return
    row = (
        db.query(NutritionLog)
        .filter(
            NutritionLog.user_id == user_id,
            NutritionLog.date == target_date,
            NutritionLog.meal_time == supplement_time,
            NutritionLog.meal_name == nutri["display"],
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()


def delete_mirror_supplement_for(db, user_id: int, target_date, meal_time, meal_name: str) -> None:
    """When a nutrition_log row that is a supplement mirror is deleted from
    the food editor, also remove its parent supplements_log entry (matched
    by date + time + canonical name)."""
    from database.models import SupplementLog

    canonical = supplement_canonical_from_display(meal_name)
    if not canonical or meal_time is None:
        return
    rows = (
        db.query(SupplementLog)
        .filter(
            SupplementLog.user_id == user_id,
            SupplementLog.date == target_date,
            SupplementLog.time == meal_time,
        )
        .all()
    )
    for row in rows:
        if normalize_supplement_name(row.supplement_name) == canonical:
            db.delete(row)
    db.commit()


def needs_legacy_migration(supplements: list) -> bool:
    """True if the supplements list is in an OLD STRUCTURAL format and needs migration.

    CRITICAL: this only triggers for FORMAT issues (missing doses, deprecated slots).
    It MUST NOT trigger because a user lacks specific supplements like K2 or Whey —
    those are personal choices, not format markers. Treating their absence as "legacy"
    wipes other users' settings with the owner's DEFAULT list (multi-user breaker).

    Empty list [] means the user explicitly cleared their supplements — do NOT migrate.
    Only migrate non-empty lists that are structurally outdated.
    """
    if not supplements:
        return False
    slots = {(it.get("slot") or "") for it in supplements if isinstance(it, dict)}
    has_long_dose = any(isinstance(it, dict) and it.get("dose") and len(it["dose"]) > 12 for it in supplements)
    no_dose = not any(isinstance(it, dict) and it.get("dose") for it in supplements)
    # post_workout slot deprecated — Whey moved to evening.
    has_deprecated_slot = "post_workout" in slots
    return no_dose or has_long_dose or has_deprecated_slot


def migrate_legacy_supplements(supplements: list) -> list:
    """Fix structural issues (deprecated slots, long doses) without altering the user's supplement list."""
    migrated = []
    for item in supplements:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        slot = item.get("slot", "morning_with")
        if slot == "post_workout":
            slot = "evening"
        dose = item.get("dose")
        if dose and len(dose) > 12:
            dose = dose[:12].strip()
        migrated.append({"name": item["name"], "slot": slot, "dose": dose})
    return migrated


def dose_from_user_schedule(supplements: list, name: str) -> Optional[str]:
    """Return the user's own planned `dose` for a supplement name, looked up in
    their configured schedule (`user_settings.supplements`). No cross-user defaults —
    multi-user platform must not stamp one user's protocol onto another."""
    target = normalize_supplement_name(name)
    for item in supplements or []:
        if isinstance(item, dict) and normalize_supplement_name(item.get("name", "")) == target:
            return item.get("dose")
    return None


# Default supplement schedule — empty; each user configures their own.
# `dose` — короткая строка для UI и для записи в supplements_log.dosage.
DEFAULT_SUPPLEMENTS: list = []

# Maps internal slot names → display labels
_SLOT_LABELS = {
    "morning_before": "☀️ УТРО (до еды)",
    "morning_with": "🌅 УТРО (с завтраком)",
    "evening": "🌙 ВЕЧЕР (с ужином)",
}


def save_supplements(items: List, user_id: int, date_str: Optional[str] = None) -> bool:
    """
    Сохраняет список принятых витаминов/БАДов в PostgreSQL.

    items может содержать строки ("Омега-3") или объекты {"name": "Омега-3", "dosage": "2000мг"}.
    Дозировка из объекта имеет приоритет над расписанием пользователя.

    Args:
        items: Список названий или объектов {name, dosage} из LLM-роутера
        user_id: Telegram ID пользователя
        date_str: Дата YYYY-MM-DD

    Returns:
        True if successful
    """
    if not items:
        return False

    user_tz = get_user_tz(user_id)
    if not date_str:
        date_str = datetime.now(user_tz).strftime("%Y-%m-%d")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    current_time = datetime.now(user_tz).time()

    db = SessionLocal()
    try:
        from database.crud import get_user_settings

        settings = get_user_settings(db, user_id)
        planned = (settings.supplements or []) if settings else []

        for item in items:
            if isinstance(item, dict):
                name = item.get("name", "")
                # LLM-extracted dosage takes priority; fall back to user schedule
                dosage = item.get("dosage") or dose_from_user_schedule(planned, name)
            else:
                name = str(item)
                dosage = dose_from_user_schedule(planned, name)

            if not name:
                continue

            create_supplement_log(
                db,
                user_id=user_id,
                date=target_date,
                time=current_time,
                supplement_name=name,
                dosage=dosage,
            )

            # If this supplement has known nutritional value — also log it as food
            # so fiber/calories/protein are counted in the daily budget
            # (e.g. psyllium → fiber, whey → protein).
            mirror_supplement_to_nutrition(db, user_id, target_date, current_time, name)

        return True
    except Exception as e:
        logger.error(f"Error saving supplements: {e}")
        return False
    finally:
        db.close()


def get_today_supplements(user_id: int, date_str: Optional[str] = None) -> List[Dict]:
    """
    Возвращает список принятого за указанную дату

    Args:
        user_id: Telegram ID пользователя
        date_str: Дата YYYY-MM-DD (если None - сегодня)

    Returns:
        List of dicts with 'name' and 'time' keys
    """
    if not date_str:
        date_str = datetime.now(get_user_tz(user_id)).strftime("%Y-%m-%d")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    db = SessionLocal()
    try:
        supplements = get_supplements_by_date(db, user_id, target_date)

        # Convert to old format for compatibility
        return [
            {
                "name": supp.supplement_name,
                "time": supp.time.strftime("%H:%M") if supp.time else "00:00",
                "source": "telegram_bot",
            }
            for supp in supplements
        ]
    finally:
        db.close()


class SupplementService:
    """Service for supplement tracking via PostgreSQL"""

    def __init__(self, user_id: int):
        """
        Initialize service for specific user

        Args:
            user_id: Telegram ID of the user
        """
        self.user_id = user_id

        # Load schedule from user_settings DB (or migrate defaults for new users)
        self.schedule = self._load_schedule()

        # Synonyms map for flexible matching
        self.synonyms = {
            "стирол": "plant sterols",
            "стиролы": "plant sterols",
            "стерол": "plant sterols",
            "стеролы": "plant sterols",
            "растительные стеролы": "plant sterols",
            "plant sterol": "plant sterols",
            "plant sterols": "plant sterols",
            "псилиум": "псиллиум",
            "псиллиум": "псиллиум",
            "psyllium": "псиллиум",
            "омега": "омега 3",
            "омега-3": "омега 3",
            "омега 3-6-9": "омега 3",
            "omega": "омега 3",
            "omega-3": "омега 3",
            "д3": "витамин d3",
            "d3": "витамин d3",
            "витамин д": "витамин d3",
            "фолат": "метилфолат",
            "метилофолат": "метилфолат",
            "фолиевая": "метилфолат",
            "folate": "метилфолат",
            "metafolin": "метилфолат",
            "methylfolate": "метилфолат",
            "5-mthf": "метилфолат",
            "креатин": "креатин",
            "creatine": "креатин",
            "creatine monohydrate": "креатин",
            "kreatin": "креатин",
            "кретин": "креатин",
            "моногидрат": "креатин",
        }

    def _load_schedule(self) -> dict:
        """Load supplement schedule from user_settings.

        Users with no configured supplements get an empty schedule (no DB write).
        Existing users whose data is structurally outdated are migrated in place.
        Returns dict: {"☀️ УТРО (до еды)": [...], "🌅 УТРО (с завтраком)": [...], "🌙 ВЕЧЕР (с ужином)": [...]}
        """
        from database.crud import get_user_settings, upsert_user_settings

        db = SessionLocal()
        try:
            settings = get_user_settings(db, self.user_id)
            if settings is None or not settings.supplements:
                raw = []
            else:
                raw = settings.supplements
                if needs_legacy_migration(raw):
                    raw = migrate_legacy_supplements(raw)
                    upsert_user_settings(db, self.user_id, supplements=raw)
        finally:
            db.close()

        result = {label: [] for label in _SLOT_LABELS.values()}
        for item in raw:
            slot = item.get("slot", "morning_with")
            name = item.get("name", "")
            label = _SLOT_LABELS.get(slot)
            if label and name:
                result[label].append({"name": name, "dose": item.get("dose")})
        return result

    def get_detailed_schedule(self, for_date: Optional[str] = None) -> str:
        """
        Returns a formatted schedule string with checkboxes for taken items

        Args:
            for_date: Date string YYYY-MM-DD (if None — today in user's timezone)
        Returns:
            Formatted schedule with ✅/⬜ checkboxes
        """
        taken_today = get_today_supplements(user_id=self.user_id, date_str=for_date)
        taken_names = {item["name"].lower() for item in taken_today}

        def is_taken(req_name: str) -> bool:
            """Check if requirement matches any taken item"""
            req_lower = req_name.lower()
            # Remove time markers for base comparison
            req_base = req_lower.replace(" (утро)", "").replace(" (вечер)", "").strip()

            for taken_name in taken_names:
                taken_lower = taken_name.lower()
                taken_base = taken_lower.replace(" (утро)", "").replace(" (вечер)", "").strip()

                # Direct match (exact)
                if taken_lower == req_lower or taken_base == req_base:
                    return True

                # Base name match (without time markers)
                if taken_base in req_base or req_base in taken_base:
                    return True

                # Synonym matching
                taken_canonical = self.synonyms.get(taken_base, taken_base)
                req_canonical = self.synonyms.get(req_base, req_base)

                if taken_canonical == req_canonical:
                    return True

                if taken_canonical in req_base or req_canonical in taken_base:
                    return True

            return False

        lines = ["💊 <b>Чек-лист витаминов на сегодня:</b>\n"]

        if not any(self.schedule.values()):
            lines.append("Список добавок не настроен.")
            lines.append("")
            lines.append("Напишите мне, что принимаете, например:")
            lines.append("<i>«Принимаю витамин D3 5000 IU и магний 2 табл вечером»</i>")
            lines.append("— и я запомню ваш протокол.")
            return "\n".join(lines)

        for time_of_day, items in self.schedule.items():
            if not items:
                continue
            lines.append(f"<b>{time_of_day}</b>")
            for item in items:
                name = item["name"] if isinstance(item, dict) else item
                dose = item.get("dose") if isinstance(item, dict) else None
                status = "✅" if is_taken(name) else "⬜"
                # Escape user-controlled name/dose — rendered into Telegram HTML parse mode.
                safe_name = html.escape(str(name))
                if dose:
                    lines.append(f"{status} <b>{safe_name}</b> — <i>{html.escape(str(dose))}</i>")
                else:
                    lines.append(f"{status} {safe_name}")
            lines.append("")  # Empty line between blocks

        return "\n".join(lines)

    def get_brief_status(self, for_date: Optional[str] = None) -> str:
        """
        Short status for /day command

        Args:
            for_date: Date string YYYY-MM-DD (if None — today in user's timezone)
        Returns:
            Brief status string with taken supplements
        """
        taken_today = get_today_supplements(user_id=self.user_id, date_str=for_date)
        if not taken_today:
            return "💊 Витамины: ❌ Не принимались"

        # Короткие имена
        short_names = {
            "plant sterols (утро)": "Стеролы↑",
            "plant sterols (вечер)": "Стеролы↓",
            "витамин d3": "D3",
            "омега 3-6-9": "Омега",
            "псиллиум": "Псиллиум",
            "магний": "Mg",
            "цинк": "Zn",
            "метилфолат": "Фолат",
        }

        names = []
        seen = set()
        for item in taken_today:
            name = item["name"].lower()
            if name not in seen:
                seen.add(name)
                short = short_names.get(name, item["name"])
                names.append(short)

        items_str = ", ".join(names)
        return f"💊 Витамины: ✅ {items_str}"


# Global instance - now requires user_id
# Create instance per-request in handlers
# supplement_service = SupplementService()  # DEPRECATED: use per-user instance


# ─── Lab-artefact detection ────────────────────────────────────────────────
# Некоторые БАДы напрямую искажают лабораторные показатели — типичный
# пример: креатин (5 г/день) поднимает сывороточный креатинин на 10-30%
# даже при идеально здоровых почках. Без явной пометки на дашборде это
# выглядит как «снижение функции почек» и приводит к ложной тревоге.
#
# Эта секция предоставляет общий helper для проверки активного приёма
# любой добавки по подстроке имени, плюс табличку известных артефактов
# биомаркеров (пока — креатин → креатинин; легко расширяется).


def is_supplement_active(db, user_id: int, name_pattern: str, days: int = 7) -> dict:
    """Активна ли добавка у пользователя в последние N дней.

    Args:
        db: SQLAlchemy session
        user_id: telegram_id пользователя
        name_pattern: подстрока для ILIKE-поиска в supplement_name
            (регистронезависимо, partial match)
        days: окно проверки, по умолчанию 7 дней. Для большинства добавок
            7 дней — разумный proxy для «принимает регулярно». Для креатина
            wash-out из организма ~10-14 дней, так что для лаб-артефакт-логики
            окно можно расширять.

    Returns:
        dict с ключами:
          active (bool): True если за окно есть хотя бы один приём
          last_date (str | None): последняя дата приёма в формате YYYY-MM-DD
          doses_in_window (int): количество записей за окно
          dose_repr (str | None): последняя зафиксированная дозировка (для UI)
    """
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            SELECT date, dosage
            FROM supplements_log
            WHERE user_id = :uid
              AND supplement_name ILIKE :pat
              AND date >= CURRENT_DATE - (:days || ' days')::interval
            ORDER BY date DESC, time DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"uid": user_id, "pat": f"%{name_pattern}%", "days": days},
    ).fetchone()

    count = (
        db.execute(
            text(
                """
            SELECT COUNT(*)
            FROM supplements_log
            WHERE user_id = :uid
              AND supplement_name ILIKE :pat
              AND date >= CURRENT_DATE - (:days || ' days')::interval
            """
            ),
            {"uid": user_id, "pat": f"%{name_pattern}%", "days": days},
        ).scalar()
        or 0
    )

    if row is None:
        return {"active": False, "last_date": None, "doses_in_window": 0, "dose_repr": None}

    last_date = row[0].isoformat() if row[0] else None
    dose_repr = row[1] if row[1] else None
    return {
        "active": True,
        "last_date": last_date,
        "doses_in_window": int(count),
        "dose_repr": dose_repr,
    }


# Таблица известных биомаркер-артефактов от добавок/еды.
# Каждый артефакт: какую subset из supplements_log искать, какие маркеры
# искажает, и насколько (для будущей коррекции в формулах).
#
# Сейчас используется только для UI-предупреждений в PhenoAge (Panel 4).
# В будущем можно подключить к корректировкам в формулах (Levine, Cockcroft,
# CKD-EPI) — но это требует валидации, поэтому пока только визуальный warning.
LAB_ARTEFACTS = {
    "creatine": {
        # Регулярный приём 5 г/день поднимает сывороточный креатинин на
        # ~10-30% (среднее ~22%). Wash-out из мышц ~10-14 дней.
        # Источники: Persky & Brazeau 2001 (Pharmacol Rev); Pritchard &
        # Kalra 1998 (Lancet); ISSN position stand 2017.
        "supplement_query": "креатин",
        "lookback_days": 14,
        "affects": {
            "creatinine": {
                "direction": "up",
                "magnitude_pct": 22,  # типичное завышение, эмпирически
                "correction_factor": 0.78,  # creatinine_real ≈ creatinine_measured × 0.78
                "explanation": (
                    "Сывороточный креатинин завышен из-за приёма креатина "
                    "({dose}). Истинная цифра приблизительно × 0.78 от "
                    "измеренной. Чтобы получить чистый результат — отменить "
                    "креатин минимум за 14 дней до сдачи."
                ),
            },
        },
    },
    # Места для будущих артефактов (без активации):
    # "biotin":  биотин → ложные значения T3/T4/TSH в иммунохем. методах
    # "alcohol_recent": алкоголь <72ч → ↑ГГТ, ↑AST, ↑ТГ
    # "bcaa":    BCAA/большой белок → ↑АЛТ слегка
}


def check_lab_artefacts_for_user(db, user_id: int) -> dict:
    """Сводка активных биомаркер-артефактов у пользователя.

    Returns:
        dict: ключи — имена артефактов из LAB_ARTEFACTS, значения — данные
        is_supplement_active + конфиг артефакта. Только активные.

    Пример возвращаемого значения для пользователя на креатине:
        {
            "creatine": {
                "active": True,
                "last_date": "2026-05-22",
                "doses_in_window": 4,
                "dose_repr": "5 г",
                "affects": {"creatinine": {...}},
            }
        }
    """
    result = {}
    for art_name, art_cfg in LAB_ARTEFACTS.items():
        status = is_supplement_active(
            db,
            user_id,
            name_pattern=art_cfg["supplement_query"],
            days=art_cfg["lookback_days"],
        )
        if status["active"]:
            result[art_name] = {**status, "affects": art_cfg["affects"]}
    return result
