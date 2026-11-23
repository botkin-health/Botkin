"""Адаптивный TDEE (maintenance) из собственных данных питания и веса.

Метод MacroFactor (https://macrofactor.com/algorithm-accuracy/): энергобаланс
закрывается по факту — сколько человек реально ел и как при этом менялся вес:

    TDEE = средний рацион − 7700 × скорость изменения веса (кг/день)

(при похудении скорость отрицательная, поэтому maintenance выше рациона).

Зачем: девайсовые оценки систематически смещены. Валидация на владельце
(15.08.2026): два независимых сегмента по 135 и 48 дней дали TDEE 2260 и 2362
при оценках Garmin 2400–2500 и старом среднем бота 1961.

Включается только когда данных достаточно (см. константы ниже); иначе
get_adaptive_tdee возвращает None и вызывающий остаётся на цепочке
Garmin/Apple/manual/default.

Защита от недолога (15.11.2026, ADR-0015). Частично внесённый день (забыл
ресторан, пиво) занижает средний рацион → оценку TDEE → цель на недели вперёд,
и в полностью внесённые дни бот показывает «перебор». На данных владельца
цель за 2 недели уехала с ~1810 до ~1410 ккал. Поэтому:
  • неполные дни исключаются: явная отметка пользователя (nutrition_day_status,
    утренний вопрос) главнее эвристики «< 70% медианы»;
  • вес не свежий → оценка замораживается на последнем взвешивании + 3 дня,
    а не экстраполируется по старым точкам;
  • цель «пользовательская» (get_adaptive_tdee) пересчитывается раз в неделю
    (по последнему закрытому воскресенью), шаг ≤100 ккал/нед, и не ниже
    BMR×1.2 по Миффлину из профиля — сидячий минимум.
"""

import logging
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from statistics import fmean, median
from typing import Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

KCAL_PER_KG_FAT = 7700  # энергетическая цена 1 кг массы тела

# Трейлинг-окно, в котором ищем данные. Шире 14-дневного среднего Garmin,
# потому что сигнал вес+рацион медленный и шумный.
WINDOW_DAYS = 42
# Минимум полных дней лога питания в окне.
MIN_LOGGED_DAYS = 21
# Минимальный разброс между первым и последним взвешиванием.
MIN_WEIGHT_SPAN_DAYS = 14
# Сглаживание веса: анкер = среднее взвешиваний в ±N дней от крайней точки.
SMOOTH_HALF_WINDOW_DAYS = 5
# День считается «не логированным целиком», если его калории < доли медианы
# логированных дней (перекус записали, остальное — нет). Было 0.5 — пропускало
# дни по 1100–1700 ккал при медиане ~2100, где забыт ресторан. Явная отметка
# пользователя (day_status) главнее этого порога в обе стороны.
MIN_DAY_KCAL_RATIO = 0.7
# Вес считается свежим ещё N дней после последнего взвешивания; дальше расчёт
# замораживается на этой дате (рацион после неё не с чем сопоставить).
STALE_WEIGHT_GRACE_DAYS = 3
# Стабилизация пользовательской цели: недельные анкеры, шаг и пол.
STABLE_WEEKS_BACK = 4
MAX_WEEKLY_STEP_KCAL = 100
BMR_FLOOR_FACTOR = 1.2
MIN_PLAUSIBLE_BMR = 1000
# Санити-границы результата: вышли за них — данные мусорные, оценке не верим.
PLAUSIBLE_TDEE_MIN = 1200
PLAUSIBLE_TDEE_MAX = 6000


def compute_adaptive_tdee(
    intake_by_day: Mapping[date_type, float],
    weights: Sequence[Tuple[date_type, float]],
    as_of: date_type,
    day_status: Optional[Mapping[date_type, bool]] = None,
) -> Optional[dict]:
    """Чистый расчёт адаптивного TDEE. None — данных мало или они мусорные.

    intake_by_day: дата → суммарные ккал за день (только дни, где лог вообще есть).
    weights: (дата, кг); допускаются несколько замеров в день и точки чуть
        за пределами окна с обеих сторон (используются для сглаживания анкеров).
    day_status: дата → True (пользователь подтвердил «внёс всё») / False («что-то
        пропустил»). Нет ключа — решает эвристика MIN_DAY_KCAL_RATIO.
    """
    day_status = day_status or {}
    requested_as_of = as_of
    # ── Свежесть веса: без взвешиваний рацион не с чем сопоставить ──────────
    past_weighings = [d for d, _ in weights if d <= as_of]
    if not past_weighings:
        return None
    as_of = min(as_of, max(past_weighings) + timedelta(days=STALE_WEIGHT_GRACE_DAYS))
    window_start = as_of - timedelta(days=WINDOW_DAYS - 1)

    # ── Вес: анкеры со сглаживанием ±5 дней ─────────────────────────────────
    in_window = sorted((d, w) for d, w in weights if window_start <= d <= as_of)
    if len(in_window) < 2:
        return None
    anchor_start_date = in_window[0][0]
    anchor_end_date = in_window[-1][0]
    span_days = (anchor_end_date - anchor_start_date).days
    if span_days < MIN_WEIGHT_SPAN_DAYS:
        return None

    def _smoothed(anchor: date_type) -> float:
        near = [w for d, w in weights if abs((d - anchor).days) <= SMOOTH_HALF_WINDOW_DAYS]
        return fmean(near)

    w_start = _smoothed(anchor_start_date)
    w_end = _smoothed(anchor_end_date)
    rate_kg_day = (w_end - w_start) / span_days

    # ── Питание: только полностью логированные дни окна ─────────────────────
    candidates = {d: kcal for d, kcal in intake_by_day.items() if window_start <= d <= as_of and (kcal or 0) > 0}
    if not candidates:
        return None
    # Медиана — только по дням без отметки «неполный», иначе дыры тянут её вниз.
    med = median([kcal for d, kcal in candidates.items() if day_status.get(d) is not False] or candidates.values())

    def _complete(d: date_type, kcal: float) -> bool:
        flag = day_status.get(d)
        if flag is not None:
            return flag
        return kcal >= MIN_DAY_KCAL_RATIO * med

    logged = {d: kcal for d, kcal in candidates.items() if _complete(d, kcal)}
    if len(logged) < MIN_LOGGED_DAYS:
        return None
    avg_intake = fmean(logged.values())

    tdee = avg_intake - KCAL_PER_KG_FAT * rate_kg_day
    if not (PLAUSIBLE_TDEE_MIN <= tdee <= PLAUSIBLE_TDEE_MAX):
        logger.warning(
            "adaptive_tdee: неправдоподобный результат %.0f (intake=%.0f, rate=%.3f кг/д) — игнорируем",
            tdee,
            avg_intake,
            rate_kg_day,
        )
        return None

    return {
        "tdee": round(tdee),
        "avg_intake": round(avg_intake),
        "weight_rate_kg_day": rate_kg_day,
        "days_used": len(logged),
        "span_days": span_days,
        "window_days": WINDOW_DAYS,
        "excluded_days": len(candidates) - len(logged),
        "as_of_effective": as_of,
        "frozen": as_of < requested_as_of,
    }


def stable_anchor(as_of: date_type) -> date_type:
    """Последнее закрытое воскресенье строго до as_of — недельный анкер цели.

    Сегодняшний (и вообще текущей недели) лог неполон по определению — день
    не закончен; анкер на закрытой неделе делает цель стабильной всю неделю.
    """
    return as_of - timedelta(days=as_of.weekday() + 1)


def compute_stable_adaptive_tdee(
    intake_by_day: Mapping[date_type, float],
    weights: Sequence[Tuple[date_type, float]],
    as_of: date_type,
    day_status: Optional[Mapping[date_type, bool]] = None,
    bmr: Optional[float] = None,
) -> Optional[dict]:
    """TDEE для цели пользователя: недельный анкер + шаг ≤ MAX_WEEKLY_STEP_KCAL + пол.

    Сырой расчёт на соседних неделях скачет на сотни ккал от ресторанной соли и
    редких взвешиваний; пользователь видит это как «вдруг надо есть меньше».
    Как у тренеров вроде MacroFactor — корректируем медленно. Пол BMR×1.2 —
    сидячий минимум: ниже него оценка почти наверняка следствие недолога.
    None — если на текущем анкере данных нет (вызывающий уходит на девайсы).
    """
    anchor = stable_anchor(as_of)
    current = compute_adaptive_tdee(intake_by_day, weights, anchor, day_status)
    if current is None:
        return None

    history = []
    for k in range(STABLE_WEEKS_BACK, 0, -1):
        r = compute_adaptive_tdee(intake_by_day, weights, anchor - timedelta(days=7 * k), day_status)
        if r is not None:
            history.append(r["tdee"])
    history.append(current["tdee"])

    value = history[0]
    for raw in history[1:]:
        value = min(max(raw, value - MAX_WEEKLY_STEP_KCAL), value + MAX_WEEKLY_STEP_KCAL)

    floor = round(bmr * BMR_FLOOR_FACTOR) if bmr and bmr >= MIN_PLAUSIBLE_BMR else None
    floored = bool(floor and value < floor)
    if floored:
        value = floor

    return {
        **current,
        "raw_tdee": current["tdee"],
        "tdee": round(value),
        "anchor": anchor,
        "floored": floored,
    }


def mifflin_bmr(sex: Optional[str], weight_kg: float, height_cm: float, age: int) -> Optional[int]:
    """BMR по Миффлину–Сан Жеору. None для неизвестного пола."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return round(base + 5)
    if sex == "female":
        return round(base - 161)
    return None


def _profile_bmr(db, user_id: int, weights: Sequence[Tuple[date_type, float]], as_of: date_type) -> Optional[int]:
    """BMR для пола цели — по формуле из профиля, НЕ по девайсу.

    Девайсовый BMR завышен (у владельца Garmin 1925 при Миффлине ~1590):
    пол от него задавил бы адаптив целиком. Нет пола/роста/даты рождения
    или взвешиваний — пола нет.
    """
    from database.models import User

    user = db.query(User).filter(User.telegram_id == user_id).first()
    past = sorted((d, w) for d, w in weights if d <= as_of)
    if not user or not user.birth_date or not user.height_cm or not past:
        return None
    born = user.birth_date
    age = as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))
    return mifflin_bmr(user.sex, past[-1][1], float(user.height_cm), age)


def get_adaptive_tdee(user_id: int, as_of: Optional[date_type] = None, db=None, stable: bool = True) -> Optional[dict]:
    """Адаптивный TDEE пользователя из Postgres (nutrition_log + weights).

    db: переиспользовать сессию вызывающего; если None — открыть свою.
    stable: True (цель пользователя) — недельный анкер, шаг, пол;
        False — сырой расчёт ровно на as_of (диагностика, тесты обвязки).
    """
    own = db is None
    if own:
        from database import SessionLocal

        db = SessionLocal()
    try:
        from core.infra.tz import get_user_tz
        from database.crud import (
            get_daily_calories_by_period,
            get_day_statuses_by_period,
            get_weights_by_period,
        )

        user_tz = get_user_tz(user_id)
        if as_of is None:
            as_of = datetime.now(user_tz).date()
        # Самый ранний недельный анкер стабилизации и его окно.
        window_start = stable_anchor(as_of) - timedelta(days=7 * STABLE_WEEKS_BACK + WINDOW_DAYS - 1)

        # Калории по дням — агрегация в SQL (окно 42 дня на каждый сейв еды,
        # тянуть все строки и суммировать в Python дорого).
        intake_by_day = get_daily_calories_by_period(db, user_id, window_start, as_of)
        day_status = get_day_statuses_by_period(db, user_id, window_start, as_of)

        # Взвешивания с запасом ±5 дней С ОБЕИХ сторон окна — для сглаживания
        # обоих анкеров. Симметрия важна при ретроспективном as_of (/day за
        # прошлую дату): без правого буфера TDEE той же даты различался бы
        # «в моменте» и задним числом. Границы — aware полночь в зоне
        # пользователя (naive-граница на TIMESTAMPTZ плавает по session tz).
        lo = datetime.combine(
            window_start - timedelta(days=SMOOTH_HALF_WINDOW_DAYS), datetime.min.time(), tzinfo=user_tz
        )
        hi = datetime.combine(as_of + timedelta(days=SMOOTH_HALF_WINDOW_DAYS + 1), datetime.min.time(), tzinfo=user_tz)
        w_rows = get_weights_by_period(db, user_id, lo, hi)

        # Дата взвешивания — локальный день пользователя: вечерний замер по UTC
        # может формально попасть на соседний день и сдвинуть анкер/span.
        # Naive measured_at (SQLite в тестах) трактуем как UTC.
        weights = []
        for w in w_rows:
            measured = w.measured_at if w.measured_at.tzinfo else w.measured_at.replace(tzinfo=timezone.utc)
            weights.append((measured.astimezone(user_tz).date(), float(w.weight)))

        if not stable:
            return compute_adaptive_tdee(intake_by_day, weights, as_of, day_status)
        bmr = _profile_bmr(db, user_id, weights, as_of)
        return compute_stable_adaptive_tdee(intake_by_day, weights, as_of, day_status=day_status, bmr=bmr)
    except Exception:
        # Фолбэк на цепочку Garmin/Apple/manual — но с трейсбеком в логе,
        # чтобы реальный баг не маскировался под «мало данных».
        logger.exception(f"get_adaptive_tdee failed for user {user_id}")
        return None
    finally:
        if own:
            db.close()
