"""Сводка «Состояние» для миниаппа: что обратить внимание + карточки потоков (GET /api/health/summary).

Чистые функции от `(db, user_id)`: никакого LLM, никаких корреляций между потоками — только
«поток против своей нормы». Окна считаются от «сегодня» в TZ пользователя (`users.timezone`).

Окна (days=7):
  * сон — включая сегодня (сегодняшняя ночь уже завершена; дата сна = день пробуждения);
  * шаги, пульс, тренировки — только ЗАВЕРШЁННЫЕ дни (сегодня исключаем: шаги за него неполные);
  * HRV — включая сегодня только у Garmin (ночное среднее), у Apple (SDNN за день) — без сегодня;
  * baseline = медиана 14 дней непосредственно ДО окна; recent = среднее по окну.

⚠️ ПОРОГИ ниже — СТАРТОВЫЕ эвристики («отклонение от своей нормы» + общеизвестные категории
АД/CGM), не клинические нормы. Их должен утвердить врач проекта до показа клинике.
Тексты `action` — плейсхолдеры (services/health_summary_texts.py).
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.health.biomarkers import load_biomarkers
from core.health.glucose_stats import GLUCOSE_STALE_THRESHOLD_MIN, TIR_LOW, compute_glucose_stats, glucose_staleness
from core.health.ref_ranges import explicit_sex, ref_range
from database.models import ActivityLog, BloodPressureLog, BloodTest, GlucoseReading, User, Weight, Workout
from services import health_summary_texts as T
from services.health_summary_schema import (
    Aggregate,
    AttentionItem,
    DataGap,
    Evidence,
    HealthSummary,
    Latest,
    LabMarker,
    LabOutOfRange,
    LabsCard,
    LabStale,
    Point,
    StreamCard,
)

# ── Пороги (НУЖНО УТВЕРДИТЬ ВРАЧУ; источник — PROPOSAL.md §4.3) ───────────────────────────────

BASELINE_DAYS = 14  # baseline = медиана 14 дн. до окна
MIN_RECENT_N = 4  # минимум точек в окне, чтобы сравнивать
MIN_BASELINE_N = 7  # минимум точек в baseline

SLEEP_ABS_LOW_H = 6.0  # эвристика: <6 ч в среднем — «мало» (общий ориентир; консенсус AASM/SRS ≥7 ч для взрослых)
SLEEP_DROP_H = 1.0  # эвристика: на 1 ч короче своей нормы
SLEEP_SHORT_NIGHT_H = 6.0  # ночь «короткая»
SLEEP_HIGH_SHORT_NIGHTS = 3  # high, если оба условия и ≥3 коротких ночи
HRV_DROP_RATIO = 0.85  # эвристика: HRV ≤ 85 % своей нормы
HR_RISE_BPM = 5  # эвристика: пульс на ≥5 уд/мин выше своей нормы
STEPS_DROP_RATIO = 0.7  # эвристика: шаги ≤ 70 % своей нормы
WORKOUT_MIN_MINUTES = 10  # короче — не считаем тренировкой
WORKOUT_PREV_WEEKS_DAYS = 28  # «история ≥3 тренировок за предыдущие 4 нед.»
WORKOUT_PREV_MIN = 3
BP_DAYS = 14
BP_MIN_N = 3
BP_HIGH = (140, 90)  # AHA/ACC 2017: «Stage 2» (≥140 или ≥90)
BP_STAGE1 = (130, 80)  # AHA/ACC 2017: «Stage 1»
BP_HIGH_MIN_COUNT = 2
GLUCOSE_TIR_MIN_PCT = 70.0  # международный консенсус CGM (Battelino 2019): TIR >70 %
GLUCOSE_TBR_MAX_PCT = 4.0  # TBR (<3,9) <4 %
GLUCOSE_EXPECTED_PER_DAY = 288  # Libre: точка ~каждые 5 мин
GLUCOSE_MIN_COVERAGE = 0.7  # ≥70 % ожидаемых точек
WEIGHT_CHANGE_PCT = 3.0  # эвристика: ≥3 % за 14 дн.
WEIGHT_CHANGE_DAYS = 14
WEIGHT_MIN_GAP_DAYS = 7  # два замера не ближе 7 дн. друг к другу
WEIGHT_STALE_DAYS = 14  # последний замер старше — карточка «stale»
LAB_HIGH_DEVIATION_PCT = 25  # отклонение >25 % от нарушенной границы у приоритетного маркера → high
LAB_PRIORITY = frozenset(
    {"ApoB", "LDL", "HbA1c", "glucose", "CRP", "hs_CRP", "ALT", "AST", "creatinine", "ferritin", "TSH", "vitamin_D"}
)
MAX_ATTENTION = 4
SEVERITY_RANK = {"high": 3, "medium": 2, "info": 1}
_SEVERITY_UP = {"info": "medium", "medium": "high", "high": "high"}

# Откуда брать данные, если поток не подключён (подсказка фронту для «Подключить»).
HINT_SOURCE = {
    "sleep": "garmin_or_apple_health",
    "activity": "garmin_or_apple_health",
    "hrv": "garmin_or_apple_health",
    "weight": "scale_or_apple_health",
    "bp": "apple_health",
    "glucose": "cgm",
    "labs": "doc_upload",
}
STREAM_ORDER = ["sleep", "activity", "hrv", "weight", "bp", "glucose", "labs"]


# ── Утилиты ───────────────────────────────────────────────────────────────────────────────────


def _family(source: Optional[str]) -> str:
    """Семейство источника: garmin_* — одно, apple* — другое (метрики HRV несопоставимы)."""
    s = (source or "").lower()
    for fam in ("garmin", "apple", "health_connect", "zepp", "withings"):
        if s.startswith(fam):
            return fam
    return s or "unknown"


def _fmt(x: Optional[float], lang: str, digits: int = 1) -> str:
    if x is None:
        return "—"
    s = f"{x:.{digits}f}"
    if digits and "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",") if lang == "ru" else s


def _iso(d: date) -> str:
    return d.isoformat()


def _win(start: date, end: date) -> str:
    return f"{start.isoformat()}..{end.isoformat()}"


def _mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _median(vals: list[float]) -> Optional[float]:
    return statistics.median(vals) if vals else None


def _user_tz(user: Optional[User]) -> ZoneInfo:
    try:
        return ZoneInfo((getattr(user, "timezone", None) or "Europe/Moscow"))
    except Exception:
        return ZoneInfo("Europe/Moscow")


def _local_date(dt: datetime, tz: ZoneInfo) -> date:
    """Дата замера в TZ пользователя (SQLite теряет tzinfo → считаем UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def _rng(end: date, days: int) -> tuple[date, date]:
    return end - timedelta(days=days - 1), end


def _in(d: date, w: tuple[date, date]) -> bool:
    return w[0] <= d <= w[1]


def _series(by_date: dict[date, float], w: tuple[date, date], by2: Optional[dict[date, float]] = None) -> list[Point]:
    out, d = [], w[0]
    while d <= w[1]:
        out.append(Point(date=_iso(d), value=by_date.get(d), value2=(by2 or {}).get(d)))
        d += timedelta(days=1)
    return out


class _Ctx:
    """Параметры прогона: язык, окно, «сегодня»."""

    def __init__(self, lang: str, days: int, today: date, tz: ZoneInfo):
        self.lang, self.days, self.today, self.tz = lang, days, today, tz
        self.units = T.UNITS.get(lang, T.UNITS["ru"])
        self.labels = T.LABELS.get(lang, T.LABELS["ru"])
        self.items = T.ITEMS.get(lang, T.ITEMS["ru"])
        self.actions = T.ACTIONS.get(lang, T.ACTIONS["ru"])

    def mean_label(self) -> str:
        return self.labels["mean"].format(days=self.days)

    def median_label(self) -> str:
        return self.labels["median"].format(bdays=BASELINE_DAYS)

    def fmt(self, x, digits=1):
        return _fmt(x, self.lang, digits)


def _agg(ctx: _Ctx, vals: list[float], kind: str, unit: str, w: tuple[date, date], digits: int = 1) -> Aggregate:
    v = _mean(vals) if kind == "mean" else _median(vals)
    return Aggregate(
        value=round(v, digits) if v is not None else None,
        unit=unit,
        kind=kind,  # type: ignore[arg-type]
        n=len(vals),
        label=ctx.mean_label() if kind == "mean" else ctx.median_label(),
        window=_win(*w),
    )


def _evidence(metric: str, recent: Aggregate, baseline: Optional[Aggregate], **extra: Any) -> Evidence:
    def pack(a: Optional[Aggregate]):
        return None if a is None else {"value": a.value, "kind": a.kind, "n": a.n, "window": a.window}

    return Evidence(metric=metric, recent=pack(recent), baseline=pack(baseline), extra=extra)


def _item(
    ctx: _Ctx,
    rule_id: str,
    stream: str,
    severity: str,
    title: str,
    detail: str,
    evidence: Evidence,
    data_date: Optional[date],
    action_key: Optional[str] = None,
) -> AttentionItem:
    return AttentionItem(
        id=rule_id,
        stream=stream,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        title=title,
        detail=detail,
        evidence=evidence,
        action=ctx.actions.get(action_key or rule_id),
        data_date=_iso(data_date) if data_date else None,
    )


# ── Запросы ───────────────────────────────────────────────────────────────────────────────────


def _activity_rows(db: Session, user_id: int, start: date, end: date) -> list[ActivityLog]:
    return list(
        db.execute(
            select(ActivityLog).where(
                ActivityLog.user_id == user_id, ActivityLog.date >= start, ActivityLog.date <= end
            )
        ).scalars()
    )


def _latest_activity(db: Session, user_id: int, col, upto: date, positive: bool = True) -> Optional[ActivityLog]:
    cond = col > 0 if positive else col.is_not(None)
    return db.execute(
        select(ActivityLog)
        .where(ActivityLog.user_id == user_id, ActivityLog.date <= upto, col.is_not(None), cond)
        .order_by(ActivityLog.date.desc())
        .limit(1)
    ).scalar_one_or_none()


# ── Карточка «числового» потока из activity_log ───────────────────────────────────────────────


def _metric_card(
    ctx: _Ctx,
    *,
    unit: str,
    digits: int,
    recent_by_date: dict[date, float],
    base_by_date: dict[date, float],
    recent_win: tuple[date, date],
    base_win: tuple[date, date],
    latest_row: Optional[tuple[date, float]],
    extra: Optional[dict] = None,
) -> StreamCard:
    """Статус/latest/avg/baseline/series для одной метрики. Не знает про правила."""
    rvals = list(recent_by_date.values())
    bvals = list(base_by_date.values())
    n = len(rvals)
    if n == 0:
        status = "stale"
    elif n < MIN_RECENT_N:
        status = "insufficient"
    else:
        status = "ok"
    last_date = latest_row[0] if latest_row else None
    return StreamCard(
        status=status,
        last_date=_iso(last_date) if last_date else None,
        stale_days=(ctx.today - last_date).days if (last_date and n == 0) else None,
        latest=Latest(value=round(latest_row[1], digits), unit=unit, date=_iso(latest_row[0])) if latest_row else None,
        avg=_agg(ctx, rvals, "mean", unit, recent_win, digits) if n else None,
        baseline=_agg(ctx, bvals, "median", unit, base_win, digits) if len(bvals) >= MIN_BASELINE_N else None,
        series=_series(recent_by_date, recent_win),
        extra=extra or {},
    )


def _sleep_stream(db, user_id, ctx: _Ctx):
    rw = _rng(ctx.today, ctx.days)
    bw = _rng(rw[0] - timedelta(days=1), BASELINE_DAYS)
    rows = _activity_rows(db, user_id, bw[0], rw[1])
    by = {r.date: float(r.sleep_hours) for r in rows if r.sleep_hours and r.sleep_hours > 0}
    last = _latest_activity(db, user_id, ActivityLog.sleep_hours, ctx.today)
    if last is None:
        return None, []
    latest = (last.date, float(last.sleep_hours))
    recent = {d: v for d, v in by.items() if _in(d, rw)}
    base = {d: v for d, v in by.items() if _in(d, bw)}
    raw = last.raw_data if isinstance(last.raw_data, dict) else {}
    deep = raw.get("deep_h", raw.get("sleep_deep_h"))
    rem = raw.get("rem_h", raw.get("sleep_rem_h"))
    extra = {
        "score": raw.get("sleep_score"),
        "deep_min": round(float(deep) * 60) if deep is not None else None,
        "rem_min": round(float(rem) * 60) if rem is not None else None,
        "source": _family(last.source),
    }
    card = _metric_card(
        ctx,
        unit=ctx.units["h"],
        digits=1,
        recent_by_date=recent,
        base_by_date=base,
        recent_win=rw,
        base_win=bw,
        latest_row=latest,
        extra=extra,
    )
    return card, _rule_sleep(ctx, card, recent, base, rw, bw)


def _rule_sleep(ctx, card, recent, base, rw, bw) -> list[AttentionItem]:
    n, bn = len(recent), len(base)
    if n < MIN_RECENT_N:
        return []
    avg7 = _mean(list(recent.values()))
    base_med = _median(list(base.values())) if bn >= MIN_BASELINE_N else None
    cond_abs = avg7 < SLEEP_ABS_LOW_H
    cond_rel = base_med is not None and avg7 <= base_med - SLEEP_DROP_H
    if not (cond_abs or cond_rel):
        return []
    short = sum(1 for v in recent.values() if v < SLEEP_SHORT_NIGHT_H)
    sev = "high" if (cond_abs and cond_rel and short >= SLEEP_HIGH_SHORT_NIGHTS) else "medium"
    title, detail = ctx.items["sleep"]
    cmp_txt = ""
    if base_med is not None:
        cmp_txt = ctx.items["sleep_cmp"].format(bdays=BASELINE_DAYS, base=ctx.fmt(base_med), bn=bn)
    ev = _evidence("sleep_hours", card.avg, card.baseline, short_nights=short)
    return [
        _item(
            ctx,
            "sleep_low_7d",
            "sleep",
            sev,
            title,
            detail.format(days=ctx.days, recent=ctx.fmt(avg7), n=n, cmp=cmp_txt),
            ev,
            _last_in(recent),
            "sleep",
        )
    ]


def _last_in(by: dict) -> Optional[date]:
    return max(by) if by else None


def _activity_stream(db, user_id, ctx: _Ctx):
    rw = _rng(ctx.today - timedelta(days=1), ctx.days)  # завершённые дни
    bw = _rng(rw[0] - timedelta(days=1), BASELINE_DAYS)
    rows = _activity_rows(db, user_id, bw[0], rw[1])
    by = {r.date: float(r.steps) for r in rows if r.steps and r.steps > 0}
    last = _latest_activity(db, user_id, ActivityLog.steps, ctx.today - timedelta(days=1))
    wk_ever = db.execute(select(Workout.id).where(Workout.user_id == user_id).limit(1)).first() is not None
    if last is None and not wk_ever:
        return None, []

    # Тренировки: только завершённые дни окна, ≥10 мин.
    prev_start = rw[0] - timedelta(days=WORKOUT_PREV_WEEKS_DAYS)
    wrows = list(
        db.execute(
            select(Workout).where(Workout.user_id == user_id, Workout.date >= prev_start, Workout.date <= rw[1])
        ).scalars()
    )
    valid = [w for w in wrows if (w.duration_minutes or 0) >= WORKOUT_MIN_MINUTES]
    in_win = [w for w in valid if _in(w.date, rw)]
    prev = [w for w in valid if prev_start <= w.date < rw[0]]
    last_wk = db.execute(
        select(Workout.date)
        .where(Workout.user_id == user_id, Workout.duration_minutes >= WORKOUT_MIN_MINUTES, Workout.date <= rw[1])
        .order_by(Workout.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    wk = {
        "count": len(in_win),
        "minutes": sum(w.duration_minutes or 0 for w in in_win),
        "last_date": _iso(last_wk) if last_wk else None,
        "prev_4w_count": len(prev),
        "min_minutes": WORKOUT_MIN_MINUTES,
        "window": _win(*rw),
    }
    recent = {d: v for d, v in by.items() if _in(d, rw)}
    base = {d: v for d, v in by.items() if _in(d, bw)}
    latest = (last.date, float(last.steps)) if last else None
    card = _metric_card(
        ctx,
        unit=ctx.units["steps"],
        digits=0,
        recent_by_date=recent,
        base_by_date=base,
        recent_win=rw,
        base_win=bw,
        latest_row=latest,
        extra={"workouts": wk},
    )
    if latest is None:  # только тренировки, шагов нет
        card.status = "ok" if in_win else "stale"
    items = _rule_activity(ctx, card, recent, base, wk, rw)
    return card, items


def _rule_activity(ctx, card, recent, base, wk, rw) -> list[AttentionItem]:
    out = []
    n, bn = len(recent), len(base)
    if n >= MIN_RECENT_N and bn >= MIN_BASELINE_N:
        avg7, med = _mean(list(recent.values())), _median(list(base.values()))
        if med and avg7 <= STEPS_DROP_RATIO * med:
            title, detail = ctx.items["activity_steps"]
            out.append(
                _item(
                    ctx,
                    "steps_low_7d",
                    "activity",
                    "info",
                    title,
                    detail.format(
                        days=ctx.days, recent=ctx.fmt(avg7, 0), n=n, base=ctx.fmt(med, 0), bdays=BASELINE_DAYS, bn=bn
                    ),
                    _evidence("steps", card.avg, card.baseline),
                    _last_in(recent),
                    "activity_steps",
                )
            )
    if ctx.days >= 7 and wk["count"] == 0 and wk["prev_4w_count"] >= WORKOUT_PREV_MIN:
        title, detail = ctx.items["activity_workouts"]
        out.append(
            _item(
                ctx,
                "workouts_none_7d",
                "activity",
                "info",
                title,
                detail.format(days=ctx.days, prev=wk["prev_4w_count"]),
                Evidence(
                    metric="workouts",
                    recent={"value": 0, "kind": "count", "n": 0, "window": wk["window"]},
                    baseline={
                        "value": wk["prev_4w_count"],
                        "kind": "count",
                        "n": wk["prev_4w_count"],
                        "window": f"{WORKOUT_PREV_WEEKS_DAYS}d before window",
                    },
                ),
                date.fromisoformat(wk["last_date"]) if wk["last_date"] else None,
                "activity_workouts",
            )
        )
    return out


def _hrv_stream(db, user_id, ctx: _Ctx):
    rw_full = _rng(ctx.today, ctx.days)
    rows = _activity_rows(db, user_id, rw_full[0] - timedelta(days=BASELINE_DAYS + 1), ctx.today)
    hrv_rows = [r for r in rows if r.hrv and r.hrv > 0]
    hr_rows = [r for r in rows if r.heart_rate_avg and r.heart_rate_avg > 0]
    last_hrv = _latest_activity(db, user_id, ActivityLog.hrv, ctx.today)
    last_hr = _latest_activity(db, user_id, ActivityLog.heart_rate_avg, ctx.today - timedelta(days=1))
    if last_hrv is None and last_hr is None:
        return None, []
    items: list[AttentionItem] = []

    def build(metric_rows, last_row, field, unit, digits, include_today_for):
        """Окно/baseline внутри одного семейства источника; сегодня — только если метрика «ночная»."""
        if last_row is None:
            return None, {}, {}, None, None
        fam = _family(last_row.source)
        rows_f = [r for r in metric_rows if _family(r.source) == fam]
        end = ctx.today if fam in include_today_for else ctx.today - timedelta(days=1)
        rw = _rng(end, ctx.days)
        bw = _rng(rw[0] - timedelta(days=1), BASELINE_DAYS)
        by = {r.date: float(getattr(r, field)) for r in rows_f}
        recent = {d: v for d, v in by.items() if _in(d, rw)}
        base = {d: v for d, v in by.items() if _in(d, bw)}
        return fam, recent, base, rw, bw

    # HRV
    fam, recent, base, rw, bw = build(hrv_rows, last_hrv, "hrv", "ms", 0, {"garmin"})
    if last_hrv is not None:
        card = _metric_card(
            ctx,
            unit=ctx.units["ms"],
            digits=0,
            recent_by_date=recent,
            base_by_date=base,
            recent_win=rw,
            base_win=bw,
            latest_row=(last_hrv.date, float(last_hrv.hrv)),
            extra={"source": fam},
        )
        if len(recent) >= MIN_RECENT_N and card.baseline is not None:
            avg7, med = _mean(list(recent.values())), card.baseline.value
            if avg7 <= HRV_DROP_RATIO * med:
                title, detail = ctx.items["hrv"]
                items.append(
                    _item(
                        ctx,
                        "hrv_low_7d",
                        "hrv",
                        "medium",
                        title,
                        detail.format(
                            days=ctx.days,
                            recent=ctx.fmt(avg7, 0),
                            n=len(recent),
                            base=ctx.fmt(med, 0),
                            bdays=BASELINE_DAYS,
                            bn=card.baseline.n,
                        ),
                        _evidence("hrv", card.avg, card.baseline, source=fam),
                        _last_in(recent),
                        "hrv",
                    )
                )
    else:
        card = StreamCard(status="stale", series=_series({}, rw_full), extra={"source": None})

    # Пульс — в extra.pulse; heart_rate_avg: пульс покоя, если он был, иначе средний за день (apple_health.py)
    pfam, precent, pbase, prw, pbw = build(hr_rows, last_hr, "heart_rate_avg", "bpm", 0, set())
    if last_hr is not None:
        pcard = _metric_card(
            ctx,
            unit=ctx.units["bpm"],
            digits=0,
            recent_by_date=precent,
            base_by_date=pbase,
            recent_win=prw,
            base_win=pbw,
            latest_row=(last_hr.date, float(last_hr.heart_rate_avg)),
        )
        raw_ok = [
            isinstance(r.raw_data, dict) and r.raw_data.get("resting_heart_rate") == r.heart_rate_avg
            for r in hr_rows
            if _family(r.source) == pfam and (_in(r.date, prw) or _in(r.date, pbw))
        ]
        kind = "resting" if raw_ok and all(raw_ok) else "mixed"
        card.extra["pulse"] = {**pcard.model_dump(), "kind": kind, "source": pfam}
        if len(precent) >= MIN_RECENT_N and pcard.baseline is not None:
            avg7, med = _mean(list(precent.values())), pcard.baseline.value
            if avg7 >= med + HR_RISE_BPM:
                title, detail = ctx.items["heart"]
                kind_txt = ctx.items["heart_kind_resting" if kind == "resting" else "heart_kind_mixed"]
                items.append(
                    _item(
                        ctx,
                        "hr_high_7d",
                        "heart",
                        "medium" if kind == "resting" else "info",
                        title,
                        detail.format(
                            kind=kind_txt,
                            days=ctx.days,
                            recent=ctx.fmt(avg7, 0),
                            n=len(precent),
                            base=ctx.fmt(med, 0),
                            bdays=BASELINE_DAYS,
                            bn=pcard.baseline.n,
                        ),
                        _evidence("heart_rate", pcard.avg, pcard.baseline, source=pfam, kind=kind),
                        _last_in(precent),
                        "heart",
                    )
                )
    if last_hrv is None:  # статус карточки — по пульсу
        p = card.extra.get("pulse")
        card.status = p["status"] if p else "stale"
    return card, items


def _weight_stream(db, user_id, ctx: _Ctx):
    rows = list(
        db.execute(
            select(Weight).where(Weight.user_id == user_id).order_by(Weight.measured_at.desc()).limit(400)
        ).scalars()
    )
    if not rows:
        return None, []
    pts = [(_local_date(r.measured_at, ctx.tz), r) for r in rows]
    pts.sort(key=lambda x: (x[0], x[1].measured_at))  # по возрастанию
    ld, lr = pts[-1]
    rw = _rng(ctx.today, ctx.days)
    in_win = [(d, r) for d, r in pts if _in(d, rw)]
    by = {}
    for d, r in in_win:
        by[d] = float(r.weight)  # последний за день (pts отсортирован)
    stale_days = (ctx.today - ld).days
    fat = next(((d, float(r.body_fat)) for d, r in reversed(pts) if r.body_fat is not None), None)
    extra: dict[str, Any] = {
        "body_fat": {"value": round(fat[1], 1), "unit": "%", "date": _iso(fat[0])} if fat else None,
        "delta": None,
    }
    if len(in_win) >= 2:
        (d0, r0), (d1, r1) = in_win[0], in_win[-1]
        extra["delta"] = {
            "from": {"date": _iso(d0), "value": float(r0.weight)},
            "to": {"date": _iso(d1), "value": float(r1.weight)},
            "kg": round(float(r1.weight) - float(r0.weight), 1),
            "kind": "first_to_last_measurement",
            "window": _win(*rw),
        }
    status = "stale" if stale_days > WEIGHT_STALE_DAYS else "ok"
    card = StreamCard(
        status=status,
        last_date=_iso(ld),
        stale_days=stale_days if status == "stale" else None,
        latest=Latest(value=round(float(lr.weight), 1), unit=ctx.units["kg"], date=_iso(ld)),
        series=_series(by, rw),
        extra=extra,
    )
    return card, _rule_weight(ctx, pts)


def _rule_weight(ctx, pts) -> list[AttentionItem]:
    w = _rng(ctx.today, WEIGHT_CHANGE_DAYS)
    in_w = [(d, r) for d, r in pts if _in(d, w)]
    if len(in_w) < 2:
        return []
    (d0, r0), (d1, r1) = in_w[0], in_w[-1]
    v0, v1 = float(r0.weight), float(r1.weight)
    if (d1 - d0).days < WEIGHT_MIN_GAP_DAYS or v0 <= 0:
        return []
    pct = (v1 - v0) / v0 * 100
    if abs(pct) < WEIGHT_CHANGE_PCT:
        return []
    title, detail = ctx.items["weight"]
    ev = Evidence(
        metric="weight",
        recent={"value": v1, "kind": "measurement", "n": 1, "window": _iso(d1)},
        baseline={"value": v0, "kind": "measurement", "n": 1, "window": _iso(d0)},
        extra={"pct": round(pct, 1)},
    )
    return [
        _item(
            ctx,
            "weight_change_14d",
            "weight",
            "info",
            title,
            detail.format(
                d0=_iso(d0),
                v0=ctx.fmt(v0),
                d1=_iso(d1),
                v1=ctx.fmt(v1),
                delta=f"{v1 - v0:+.1f}".replace(".", ",") if ctx.lang == "ru" else f"{v1 - v0:+.1f}",
                pct=ctx.fmt(pct),
            ),
            ev,
            d1,
            "weight",
        )
    ]


def _bp_stream(db, user_id, ctx: _Ctx):
    ever = db.execute(select(BloodPressureLog.id).where(BloodPressureLog.user_id == user_id).limit(1)).first()
    if ever is None:
        return None, []
    rows = list(
        db.execute(
            select(BloodPressureLog)
            .where(BloodPressureLog.user_id == user_id)
            .order_by(BloodPressureLog.measured_at.desc())
            .limit(200)
        ).scalars()
    )
    # Заглушки/нули (см. cleanup_bp_placeholders) отбрасываем.
    pts = sorted(
        [
            (_local_date(r.measured_at, ctx.tz), r)
            for r in rows
            if r.systolic and r.diastolic and r.systolic > 0 and r.diastolic > 0
        ],
        key=lambda x: (x[0], x[1].measured_at),
    )
    if not pts:
        return None, []
    w = _rng(ctx.today, BP_DAYS)
    win = [(d, r) for d, r in pts if _in(d, w)]
    ld, lr = pts[-1]
    n = len(win)
    sys_by, dia_by = {}, {}
    per_day: dict[date, list] = {}
    rw = _rng(ctx.today, ctx.days)
    for d, r in pts:
        if _in(d, rw):
            per_day.setdefault(d, []).append(r)
    for d, rs in per_day.items():
        sys_by[d] = round(sum(x.systolic for x in rs) / len(rs), 1)
        dia_by[d] = round(sum(x.diastolic for x in rs) / len(rs), 1)
    cnt_high = sum(1 for _, r in win if r.systolic >= BP_HIGH[0] or r.diastolic >= BP_HIGH[1])
    avg_s = _mean([float(r.systolic) for _, r in win])
    avg_d = _mean([float(r.diastolic) for _, r in win])
    status = "stale" if n == 0 else ("insufficient" if n < BP_MIN_N else "ok")
    unit = ctx.units["mmhg"]
    card = StreamCard(
        status=status,
        last_date=_iso(ld),
        stale_days=(ctx.today - ld).days if n == 0 else None,
        latest=Latest(value=float(lr.systolic), value2=float(lr.diastolic), unit=unit, date=_iso(ld)),
        avg=Aggregate(
            value=round(avg_s, 0),
            value2=round(avg_d, 0),
            unit=unit,
            kind="mean",
            n=n,
            label=ctx.labels["mean"].format(days=BP_DAYS),
            window=_win(*w),
        )
        if n
        else None,
        series=_series(sys_by, rw, dia_by),
        extra={"count_ge_140_90": cnt_high, "n": n, "window_days": BP_DAYS},
    )
    items: list[AttentionItem] = []
    if n >= BP_MIN_N:
        ev = Evidence(
            metric="blood_pressure",
            recent={"value": round(avg_s), "value2": round(avg_d), "kind": "mean", "n": n, "window": _win(*w)},
            extra={"count_ge_140_90": cnt_high},
        )
        if cnt_high >= BP_HIGH_MIN_COUNT:
            title, detail = ctx.items["bp_high"]
            items.append(
                _item(
                    ctx,
                    "bp_high_14d",
                    "bp",
                    "high",
                    title,
                    detail.format(bp_days=BP_DAYS, cnt=cnt_high, n=n),
                    ev,
                    ld,
                    "bp_high",
                )
            )
        elif avg_s >= BP_STAGE1[0] or avg_d >= BP_STAGE1[1]:
            title, detail = ctx.items["bp_avg"]
            items.append(
                _item(
                    ctx,
                    "bp_avg_14d",
                    "bp",
                    "medium",
                    title,
                    detail.format(bp_days=BP_DAYS, sys=round(avg_s), dia=round(avg_d), n=n),
                    ev,
                    ld,
                    "bp_avg",
                )
            )
    return card, items


def _glucose_stream(db, user_id, ctx: _Ctx, now: Optional[datetime] = None):
    last = db.execute(
        select(GlucoseReading).where(GlucoseReading.user_id == user_id).order_by(GlucoseReading.ts.desc()).limit(1)
    ).scalar_one_or_none()
    if last is None:
        return None, []
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=ctx.days)  # скользящее окно по времени, а не по датам: неполного «дня» нет
    rows = list(
        db.execute(
            select(GlucoseReading)
            .where(GlucoseReading.user_id == user_id, GlucoseReading.ts >= since)
            .order_by(GlucoseReading.ts)
        ).scalars()
    )
    vals = [float(r.value) for r in rows]
    n = len(vals)
    stats = compute_glucose_stats(vals)
    stale = glucose_staleness(last.ts, now)
    ld = _local_date(last.ts, ctx.tz)
    expected = ctx.days * GLUCOSE_EXPECTED_PER_DAY
    enough = n >= GLUCOSE_MIN_COVERAGE * expected
    status = "stale" if n == 0 else ("ok" if enough else "insufficient")
    per_day: dict[date, list[float]] = {}
    for r in rows:
        per_day.setdefault(_local_date(r.ts, ctx.tz), []).append(float(r.value))
    by = {d: round(sum(v) / len(v), 2) for d, v in per_day.items()}
    unit = ctx.units["mmol"]
    card = StreamCard(
        status=status,
        last_date=_iso(ld),
        stale_days=(ctx.today - ld).days if n == 0 else None,
        latest=Latest(value=round(float(last.value), 1), unit=unit, date=_iso(ld)),
        avg=Aggregate(value=stats.get("avg"), unit=unit, kind="mean", n=n, label=ctx.mean_label()) if n else None,
        series=_series(by, _rng(ctx.today, ctx.days)),
        extra={
            "n": n,
            "expected_n": expected,
            "coverage_pct": round(100 * n / expected, 1) if expected else None,
            "tir_pct": stats.get("tir_pct"),
            "tbr_pct": stats.get("below_pct"),
            "tar_pct": stats.get("above_pct"),
            "last_point_age_min": stale["last_point_age_min"],
            "is_stale": stale["is_stale"],
            "stale_threshold_min": GLUCOSE_STALE_THRESHOLD_MIN,
        },
    )
    items: list[AttentionItem] = []
    if status == "ok":
        recent = {"kind": "mean", "n": n}
        if stats["tir_pct"] < GLUCOSE_TIR_MIN_PCT:
            title, detail = ctx.items["glucose_tir"]
            items.append(
                _item(
                    ctx,
                    "glucose_tir_low",
                    "glucose",
                    "medium",
                    title,
                    detail.format(tir=ctx.fmt(stats["tir_pct"]), days=ctx.days, n=n),
                    Evidence(metric="glucose_tir_pct", recent={**recent, "value": stats["tir_pct"]}),
                    ld,
                    "glucose_tir",
                )
            )
        if stats["below_pct"] >= GLUCOSE_TBR_MAX_PCT:
            title, detail = ctx.items["glucose_tbr"]
            items.append(
                _item(
                    ctx,
                    "glucose_tbr_high",
                    "glucose",
                    "medium",
                    title,
                    detail.format(tbr=ctx.fmt(stats["below_pct"]), days=ctx.days, n=n),
                    Evidence(
                        metric="glucose_tbr_pct",
                        recent={**recent, "value": stats["below_pct"]},
                        extra={"threshold": TIR_LOW},
                    ),
                    ld,
                    "glucose_tbr",
                )
            )
    return card, items


# ── Анализы ───────────────────────────────────────────────────────────────────────────────────


def _labs_stream(db, user_id, ctx: _Ctx, sex: Optional[str]):
    from core.reports.biomarker_dynamics import MARKER_CONFIG

    if db.execute(select(BloodTest.id).where(BloodTest.user_id == user_id).limit(1)).first() is None:
        return None, []
    bio = load_biomarkers(db, user_id)
    recs = {k: v for k, v in bio.items() if not k.startswith("_")}
    if not recs:
        return None, []
    en = ctx.lang == "en"
    markers: list[LabMarker] = []
    out: list[LabOutOfRange] = []
    stale: list[LabStale] = []
    for key, cfg in MARKER_CONFIG.items():
        rec = recs.get(key)
        if rec is None or not isinstance(rec.get("value"), (int, float)):
            continue
        label = cfg.get("label_en", cfg["label"]) if en else cfg["label"]
        unit = cfg.get("unit_en", cfg["unit"]) if en else cfg["unit"]
        val = float(rec["value"])
        bounds = ref_range(key, sex)
        is_stale = bool(rec.get("is_stale"))
        flag = "" if (bounds is None or is_stale) else _flag(val, bounds)
        m = LabMarker(
            key=key,
            label=label,
            value=val,
            unit=unit,
            date=rec["date"],
            days_ago=rec.get("days_ago"),
            ref_low=bounds[0] if bounds else None,
            ref_high=bounds[1] if bounds else None,
            flag=flag,
        )
        markers.append(m)
        if is_stale and rec.get("days_ago") is not None:
            stale.append(
                LabStale(
                    key=key,
                    label=label,
                    days_ago=rec["days_ago"],
                    threshold_days=rec["staleness_threshold_days"],
                    last_date=rec["date"],
                )
            )
        if flag and bounds:
            direction = "high" if flag == "↑" else "low"
            bound = bounds[1] if direction == "high" else bounds[0]
            dev = int(round(abs(val - bound) / bound * 100)) if bound else 0
            hist = rec.get("history") or []
            worse = False
            if len(hist) >= 2:
                prev = hist[-2]["value"]
                worse = val > prev if direction == "high" else val < prev
            sev = "high" if (key in LAB_PRIORITY and dev > LAB_HIGH_DEVIATION_PCT) else "medium"
            if worse:  # L3: вне нормы и ухудшение к предыдущему замеру
                sev = _SEVERITY_UP[sev]
            out.append(
                LabOutOfRange(**m.model_dump(), direction=direction, deviation_pct=dev, severity=sev, history=hist)
            )  # type: ignore[arg-type]
    stale.sort(key=lambda s: -s.days_ago)
    last_dates = [r["date"] for r in recs.values() if r.get("date")]
    last_test = max(last_dates) if last_dates else None
    if sex is None:
        note = ctx.labels["ref_sex_not_set"]
    elif sex == "male":
        note = ctx.labels["ref_male"]
    else:
        note = ctx.labels["ref_male_only"]
    status = "attention" if out else ("stale" if stale else "ok")
    stale_days = None
    if last_test:
        try:
            stale_days = (ctx.today - date.fromisoformat(last_test)).days
        except ValueError:
            pass
    card = LabsCard(
        status=status,
        last_date=last_test,
        stale_days=stale_days,
        last_test_date=last_test,
        n_markers=len(recs),
        markers=markers,
        out_of_range=out,
        stale=stale,
        ref_note=note,
    )  # type: ignore[arg-type]
    items = _rules_labs(ctx, out, stale, last_test)
    return card, items


def _flag(val: float, bounds: tuple[float, float]) -> str:
    return "↑" if val > bounds[1] else ("↓" if val < bounds[0] else "")


def _rules_labs(ctx, out: list[LabOutOfRange], stale: list[LabStale], last_test: Optional[str]) -> list[AttentionItem]:
    items = []
    for o in out:
        key = "lab_high" if o.direction == "high" else "lab_low"
        title, detail = ctx.items[key]
        ref = o.ref_high if o.direction == "high" else o.ref_low
        d = detail.format(value=ctx.fmt(o.value, 2), unit=o.unit, date=o.date, ref=ctx.fmt(ref, 2))
        if len(o.history) >= 2:
            d += ctx.items["lab_prev"].format(prev=ctx.fmt(o.history[-2]["value"], 2))
        ev = Evidence(
            metric=o.key,
            recent={"value": o.value, "kind": "measurement", "n": 1, "window": o.date},
            baseline=(
                {"value": o.history[-2]["value"], "kind": "measurement", "n": 1, "window": o.history[-2]["date"]}
                if len(o.history) >= 2
                else None
            ),
            extra={"deviation_pct": o.deviation_pct, "ref_low": o.ref_low, "ref_high": o.ref_high},
        )
        action = ctx.actions.get(f"lab:{o.key}") or ctx.actions["lab:_default"]
        items.append(
            AttentionItem(
                id=f"lab_{o.key}",
                stream="labs",
                severity=o.severity,
                title=title.format(label=o.label),
                detail=d,
                evidence=ev,
                action=action,
                data_date=o.date,
            )
        )
    if stale:
        title, detail = ctx.items["labs_stale"]
        names = ", ".join(s.label for s in stale[:5]) + ("…" if len(stale) > 5 else "")
        items.append(
            AttentionItem(
                id="labs_stale",
                stream="labs",
                severity="info",
                title=title.format(n=len(stale)),
                detail=detail.format(names=names),
                evidence=Evidence(metric="labs_stale", extra={"n": len(stale), "keys": [s.key for s in stale]}),
                action=ctx.actions["lab_stale"],
                data_date=last_test,
            )
        )
    return items


# ── Сборка ────────────────────────────────────────────────────────────────────────────────────


def rank_attention(items: list[AttentionItem], limit: int = MAX_ATTENTION) -> list[AttentionItem]:
    """severity (high > medium > info), затем свежесть данных (новее — выше); максимум `limit`."""
    return sorted(items, key=lambda i: (-SEVERITY_RANK[i.severity], _neg_date(i.data_date)))[:limit]


def _neg_date(s: Optional[str]) -> int:
    return -date.fromisoformat(s).toordinal() if s else 0


def build_summary_text(ctx: _Ctx, attention: list[AttentionItem], streams: dict, n_labs_stale: int) -> str:
    t = T.SUMMARY.get(ctx.lang, T.SUMMARY["ru"])
    names: list[str] = []
    for it in attention:
        n = ctx.labels["stream"][it.stream]
        if it.id != "labs_stale" and n not in names:
            names.append(n)
    parts = []
    if names:
        parts.append(t["attention"].format(streams=", ".join(names)))
    if n_labs_stale:
        parts.append(t["labs_stale"].format(n=n_labs_stale))
    if not parts:
        comparable = any(c.status in ("ok", "attention") for c in streams.values())
        parts.append(t["calm"].format(days=ctx.days) if comparable else t["no_data"])
    return " ".join(parts)


def build_health_summary(
    db: Session,
    user_id: int,
    *,
    days: int = 7,
    lang: str = "ru",
    today: Optional[date] = None,
    now: Optional[datetime] = None,
) -> HealthSummary:
    """Единая сводка. `today`/`now` — для тестов (по умолчанию — сегодня в TZ пользователя)."""
    days = max(7, min(30, int(days)))
    user = db.execute(select(User).where(User.telegram_id == user_id)).scalar_one_or_none()
    if user is None:
        return HealthSummary(
            window_days=days, lang=lang, onboarding=True, summary_text=T.SUMMARY.get(lang, T.SUMMARY["ru"])["no_data"]
        )
    tz = _user_tz(user)
    today = today or datetime.now(tz).date()
    ctx = _Ctx(lang, days, today, tz)
    sex = explicit_sex(user.onboarding_data)  # users.sex на дефолте 'male' не считается заданным

    builders = {
        "sleep": lambda: _sleep_stream(db, user_id, ctx),
        "activity": lambda: _activity_stream(db, user_id, ctx),
        "hrv": lambda: _hrv_stream(db, user_id, ctx),
        "weight": lambda: _weight_stream(db, user_id, ctx),
        "bp": lambda: _bp_stream(db, user_id, ctx),
        "glucose": lambda: _glucose_stream(db, user_id, ctx, now),
        "labs": lambda: _labs_stream(db, user_id, ctx, sex),
    }
    streams: dict[str, Any] = {}
    all_items: list[AttentionItem] = []
    gaps: list[DataGap] = []
    for name in STREAM_ORDER:
        card, items = builders[name]()
        if card is None:
            gaps.append(DataGap(stream=name, reason="not_connected", hint_source=HINT_SOURCE[name]))
            continue
        all_items.extend(items)
        if any(i.stream == name or (name == "hrv" and i.stream == "heart") for i in items) and card.status in (
            "ok",
            "stale",
            "insufficient",
        ):
            card.status = "attention"
        streams[name] = card
        if card.status == "insufficient":
            n = (card.avg.n if card.avg else 0) if name != "labs" else None
            gaps.append(DataGap(stream=name, reason="insufficient", n=n))
        elif card.status == "stale":
            gaps.append(DataGap(stream=name, reason="stale", n=None))
    if "labs" in streams and sex is None:
        gaps.append(DataGap(stream="labs", reason="sex_not_set"))

    attention = rank_attention(all_items)
    labs = streams.get("labs")
    return HealthSummary(
        as_of=_iso(today),
        tz=str(tz),
        window_days=days,
        lang=lang,
        sex=sex,  # type: ignore[arg-type]
        attention=attention,
        summary_text=build_summary_text(ctx, attention, streams, len(labs.stale) if labs else 0),
        streams=streams,
        data_gaps=gaps,
    )
