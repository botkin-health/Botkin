"""Agent tools: supplement logging and history."""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db, require_agent_scope
from .common import _parse_date

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-supplements"])


class LogSupplementRequest(BaseModel):
    supplement_name: str
    dosage: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    time: Optional[str] = None  # HH:MM
    force: bool = False  # True — записать даже если та же добавка уже логировалась в этот день


def _parse_time(time_str: Optional[str]):
    """Parse HH:MM string or return None."""
    if not time_str:
        return None
    from datetime import time as time_cls

    try:
        h, m = time_str.split(":")
        return time_cls(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {time_str!r}. Use HH:MM.")


@router.post("/log_supplement")
async def log_supplement(
    req: LogSupplementRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Save a supplement entry to supplements_log."""
    from sqlalchemy import text as _text

    from database.crud import create_supplement_log

    record_date = _parse_date(req.date, user)
    sup_time = _parse_time(req.time)

    # Дедуп-guard (F-002, 02.07.2026): та же добавка уже логировалась в этот день →
    # не пишем молча дубль, а возвращаем warning; агент уточнит у пользователя
    # и при подтверждении повторит вызов с force=true.
    if not req.force:
        existing = db.execute(
            _text(
                "SELECT id, time FROM supplements_log "
                "WHERE user_id = :uid AND date = :d "
                "AND LOWER(REPLACE(supplement_name, '-', ' ')) = LOWER(REPLACE(:name, '-', ' ')) "
                "LIMIT 1"
            ),
            {"uid": user.telegram_id, "d": record_date, "name": req.supplement_name},
        ).first()
        if existing:
            return {
                "status": "duplicate_warning",
                "existing_id": existing.id,
                "existing_time": str(existing.time) if existing.time else None,
                "date": record_date.isoformat(),
                "supplement_name": req.supplement_name,
                "hint": (
                    "Эта добавка уже залогирована в этот день. Запись НЕ создана. "
                    "Спроси пользователя, действительно ли это повторный приём; "
                    "если да — повтори вызов с force=true."
                ),
            }

    log = create_supplement_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        time=sup_time,
        supplement_name=req.supplement_name,
        dosage=req.dosage,
    )

    result = {
        "status": "ok",
        "supplement_id": log.id,
        "date": record_date.isoformat(),
        "supplement_name": req.supplement_name,
        "dosage": req.dosage,
    }

    # Отметка приёма — это событие, а не вопрос: пользователь ничего не
    # спрашивает, поэтому сам агент про фармакогенетику не вспомнит. Если по
    # препарату есть находка ДНК-теста, отдаём её вместе с подтверждением
    # записи, чтобы предупреждение прозвучало В МОМЕНТ приёма, а не когда-нибудь
    # потом. Сбой чтения генетики не должен ломать логирование.
    try:
        from core.health.genetics import check_drug

        finding = check_drug(user, req.supplement_name)
        if finding:
            result["pharmacogenetics"] = finding
            result["hint"] = (
                "По этому препарату есть находка ДНК-теста (см. pharmacogenetics). "
                "Обязательно скажи о ней пользователю прямо сейчас, вместе с "
                "подтверждением записи, и назови ген-основание."
            )
    except Exception:
        logger.exception("log_supplement: проверка фармакогенетики не удалась для %s", req.supplement_name)

    return result


@router.get("/recent_supplements")
async def recent_supplements(
    days: int = 30,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent supplement intake log with per-supplement aggregation.

    Reads from `supplements_log` (filled by aiogram bot when user logs
    "выпил магний" etc). Returns:
      - per-supplement: days_taken in period, total_intakes (multi-dose/day OK),
        last_taken_date, last_dosage seen
      - period stats: total log lines

    Default 30 days — typical regimen feedback window.
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    sql = sql_text(
        """
        SELECT supplement_name,
               COUNT(*)                          AS total_intakes,
               COUNT(DISTINCT date)              AS days_taken,
               MAX(date)                         AS last_date,
               (ARRAY_AGG(dosage ORDER BY date DESC, time DESC NULLS LAST))[1] AS last_dosage
        FROM supplements_log
        WHERE user_id = :uid
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        GROUP BY supplement_name
        ORDER BY days_taken DESC, supplement_name
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "supplement": r.supplement_name,
            "days_taken": r.days_taken,
            "total_intakes": r.total_intakes,
            "intakes_per_day_avg": round(r.total_intakes / r.days_taken, 2) if r.days_taken else 0,
            "adherence_pct": round(100 * r.days_taken / days, 1),
            "last_date": r.last_date.isoformat() if r.last_date else None,
            "last_dosage": r.last_dosage,
        }
        for r in rows
    ]
    return {
        "status": "ok",
        "period_days": days,
        "unique_supplements": len(items),
        "total_log_entries": sum(i["total_intakes"] for i in items),
        "items": items,
    }


_BRACKETS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_DOSE_TAIL_RE = re.compile(
    r"\s*(\d+(?:[.,]\d+)?\s*(?:мкг|мг|мл|ме|г|mcg|mg|ml|iu|ug|µg|g|таб\w*|tab\w*|капс\w*|caps?\w*|шт\w*))\.?\s*$",
    re.IGNORECASE,
)


def _supplement_group_key(raw: str) -> tuple:
    """(ключ группировки, доза из хвоста имени | None).

    lower, без содержимого скобок, без хвоста-дозы, схлопнутые пробелы,
    затем синонимы из core.health.supplements.
    """
    from core.health.supplements import normalize_supplement_name

    name = _BRACKETS_RE.sub(" ", raw or "")
    name = " ".join(name.split())
    dose = None
    m = _DOSE_TAIL_RE.search(name)
    if m:
        dose = " ".join(m.group(1).split())
        name = name[: m.start()].strip()
    key = normalize_supplement_name(name) or (raw or "").strip().lower()
    return key, dose


class EditSupplementLogRequest(BaseModel):
    date: Optional[str] = None  # YYYY-MM-DD, дата ЗАПИСАННОГО приёма (обязательна без log_id)
    supplement: Optional[str] = None  # имя добавки (обязательно без log_id)
    dosage_from: Optional[str] = None  # текущая доза строки — сузить выбор, если в день их несколько
    log_id: Optional[int] = None  # точный id строки из candidates (имеет приоритет над поиском)
    # Действия (одно из группы изменений либо delete):
    new_dosage: Optional[str] = None
    new_date: Optional[str] = None
    new_supplement_name: Optional[str] = None
    delete: bool = False


def _norm_dose(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _supplement_row_dict(r) -> dict:
    return {
        "id": r.id,
        "date": r.date.isoformat() if r.date else None,
        "time": r.time.strftime("%H:%M") if r.time else None,
        "supplement_name": r.supplement_name,
        "dosage": r.dosage,
    }


@router.post("/edit_supplement_log")
async def edit_supplement_log(
    req: EditSupplementLogRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Исправить или удалить УЖЕ записанный приём добавки.

    Находит строку пользователя по (date, supplement[, dosage_from]) либо по log_id
    и применяет одно действие: new_dosage / new_date / new_supplement_name / delete.
    0 строк → status=not_found + candidates (±3 дня); >1 → status=ambiguous + candidates,
    ничего не меняется (повторить с log_id). Только строки текущего пользователя.
    """
    from database.models import SupplementLog

    has_change = any(v is not None for v in (req.new_dosage, req.new_date, req.new_supplement_name))
    if not has_change and not req.delete:
        raise HTTPException(
            status_code=422,
            detail="Не указано действие: new_dosage, new_date, new_supplement_name или delete=true.",
        )
    if req.delete and has_change:
        raise HTTPException(status_code=422, detail="delete нельзя совмещать с изменением полей.")
    if req.new_supplement_name is not None and not req.new_supplement_name.strip():
        raise HTTPException(status_code=422, detail="new_supplement_name не может быть пустым.")

    new_date = None
    if req.new_date is not None:
        new_date = _parse_date(req.new_date, user)
        tz_name = getattr(user, "timezone", None) or "Europe/Moscow"
        try:
            user_tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            user_tz = ZoneInfo("Europe/Moscow")
        if new_date > datetime.now(user_tz).date():
            raise HTTPException(status_code=422, detail="new_date не может быть в будущем.")

    base = db.query(SupplementLog).filter(SupplementLog.user_id == user.telegram_id)

    if req.log_id is not None:
        matches = base.filter(SupplementLog.id == req.log_id).all()
        if not matches:
            return {"status": "not_found", "candidates": []}
    else:
        if not req.date or not (req.supplement or "").strip():
            raise HTTPException(status_code=422, detail="Нужны date и supplement (либо log_id).")
        day = _parse_date(req.date, user)
        want = req.supplement.strip()
        want_key, _ = _supplement_group_key(want)
        want_low = want.lower()

        def _similar(name: str) -> bool:
            key, _d = _supplement_group_key(name)
            low = (name or "").lower()
            return key == want_key or want_low in low or want_key in key or key in want_key

        day_rows = base.filter(SupplementLog.date == day).order_by(SupplementLog.time, SupplementLog.id).all()
        matches = [r for r in day_rows if _supplement_group_key(r.supplement_name)[0] == want_key]
        if not matches:
            matches = [r for r in day_rows if want_low in (r.supplement_name or "").lower()]
        if req.dosage_from and len(matches) > 1:
            nd = _norm_dose(req.dosage_from)
            narrowed = [r for r in matches if _norm_dose(r.dosage) == nd]
            if not narrowed:
                narrowed = [r for r in matches if nd and nd in _norm_dose(r.dosage)]
            if narrowed:
                matches = narrowed

        if not matches:
            near = (
                base.filter(
                    SupplementLog.date >= day - timedelta(days=3),
                    SupplementLog.date <= day + timedelta(days=3),
                )
                .order_by(SupplementLog.date, SupplementLog.time, SupplementLog.id)
                .all()
            )
            return {
                "status": "not_found",
                "candidates": [_supplement_row_dict(r) for r in near if _similar(r.supplement_name)],
            }

    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": [_supplement_row_dict(r) for r in matches]}

    row = matches[0]
    before = _supplement_row_dict(row)
    if req.delete:
        db.delete(row)
        db.commit()
        return {"status": "ok", "action": "deleted", "before": before, "after": None}

    if req.new_dosage is not None:
        row.dosage = req.new_dosage.strip() or None
    if new_date is not None:
        row.date = new_date
    if req.new_supplement_name is not None:
        row.supplement_name = req.new_supplement_name.strip()
    db.commit()
    db.refresh(row)
    return {"status": "ok", "action": "updated", "before": before, "after": _supplement_row_dict(row)}


@router.get("/supplement_daily_log")
async def supplement_daily_log(
    days: int = 30,
    supplement: Optional[str] = None,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Per-day supplement intake log for correlation analysis.

    В отличие от /recent_supplements (только агрегаты), возвращает для каждой
    добавки СПИСОК ДАТ приёма за окно + границы окна — чтобы сопоставлять факт
    приёма по дням с данными сна/HRV/активности (напр. магний ↔ качество сна).

    supplements_log хранит строку на каждый приём; «не принимал» = отсутствие
    строки. Отдаём разреженно: taken_dates + [start_date, end_date] полностью
    определяют taken/not-taken для любого дня без плотной сетки N×дни.

    Группировка — по нормализованному имени (lower, без скобок и без хвоста-дозы
    вида «0.5 мг»/«500mg»/«1 таб»), поэтому разные написания одного препарата
    сливаются в одну группу; оригинальные имена — в name_variants (если их >1).

    Дозы по датам: если в группе больше одного уникального значения дозы —
    отдаётся `intakes` [{date, time, dosage}] (каждая строка лога, хронологически;
    dosage берётся из строки, а если пусто — из хвоста-дозы в имени). Если доза
    одна (или её нет) — `dosage_constant: true` без intakes, чтобы ответ не
    раздувался (ежедневные добавки за 180 дней). `last_dosage` — только
    ПОСЛЕДНЯЯ доза, на прошлые даты её распространять нельзя.

    Параметры:
      days: окно, 1..180 (дефолт 30).
      supplement: опц. подстрока ОРИГИНАЛЬНОГО имени (регистронезависимо).
    """
    from datetime import time as _dtime

    from database.models import SupplementLog

    days = max(1, min(days, 180))
    # «Сегодня» в tz пользователя — иначе поздние вечерние записи уедут за окно
    # (та же логика, что в других эндпоинтах агента).
    tz_name = getattr(user, "timezone", None) or "Europe/Moscow"
    try:
        user_tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        user_tz = ZoneInfo("Europe/Moscow")
    today = datetime.now(user_tz).date()
    start_date = today - timedelta(days=days - 1)

    rows = (
        db.query(
            SupplementLog.supplement_name,
            SupplementLog.date,
            SupplementLog.time,
            SupplementLog.dosage,
        )
        .filter(
            SupplementLog.user_id == user.telegram_id,
            SupplementLog.date >= start_date,
        )
        .order_by(SupplementLog.supplement_name, SupplementLog.date)
        .all()
    )

    name_filter = supplement.strip().lower() if supplement else None

    # Группируем по НОРМАЛИЗОВАННОМУ ключу: один препарат часто записан под
    # несколькими именами («Витамин B12», «Витамин B12 (цианокобаламин) 0.5 мг»).
    groups: dict = {}
    for r in sorted(rows, key=lambda x: (x.date, x.time or _dtime.min)):
        name = r.supplement_name or ""
        if name_filter and name_filter not in name.lower():
            continue
        key, name_dose = _supplement_group_key(name)
        g = groups.setdefault(key, {"dates": set(), "names": {}, "intakes": []})
        g["dates"].add(r.date)
        g["names"][name] = g["names"].get(name, 0) + 1
        g["intakes"].append(
            {
                "date": r.date.isoformat(),
                "time": r.time.strftime("%H:%M") if r.time else None,
                # Доза из строки; если пусто — доза, зашитая в имя («... 0.5 мг»).
                "dosage": r.dosage or name_dose,
            }
        )

    supplements = []
    for g in groups.values():
        dates_sorted = sorted(g["dates"])
        # Самое частое оригинальное имя (при равенстве — первое встреченное).
        names_by_freq = sorted(g["names"], key=lambda n: -g["names"][n])
        item = {
            "supplement": names_by_freq[0],
            "days_taken": len(dates_sorted),
            "adherence_pct": round(100 * len(dates_sorted) / days, 1),
            "taken_dates": [d.isoformat() for d in dates_sorted],
            # Только ПОСЛЕДНЯЯ доза (intakes отсортированы хронологически).
            "last_dosage": g["intakes"][-1]["dosage"],
        }
        if len(names_by_freq) > 1:
            item["name_variants"] = names_by_freq
        # Сравниваем дозы без пробелов и регистра («1мг» == «1 мг»), пустые не в счёт:
        # иначе у ежедневной добавки с изредка пустой дозой intakes раздувается на всё окно.
        distinct = {re.sub(r"\s+", "", i["dosage"]).lower() for i in g["intakes"] if i["dosage"]}
        if len(distinct) > 1:
            item["intakes"] = g["intakes"]
        else:
            item["dosage_constant"] = True
        supplements.append(item)
    # По убыванию частоты, затем по имени — как в /recent_supplements.
    supplements.sort(key=lambda s: (-s["days_taken"], s["supplement"]))

    return {
        "status": "ok",
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "unique_supplements": len(supplements),
        "supplements": supplements,
    }
