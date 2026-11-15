"""Адаптивный TDEE по методу MacroFactor (#358, 15.08.2026).

TDEE (maintenance) выводится из собственных данных пользователя:
    TDEE = средний фактический рацион − 7700 × скорость изменения веса (кг/день)

Девайсовые оценки (Garmin/Apple) систематически смещены: у владельца Garmin
показывал 2400–2500, старое среднее бота — 1961, а два независимых сегмента
питание+вес (135 и 48 дней) дали 2260 и 2362. Адаптивная оценка честнее,
потому что закрывает энергобаланс по факту.

Условия включения: ≥21 полный день лога питания и ≥2 взвешивания с разбросом
≥14 дней внутри окна. Иначе — None (вызывающий откатывается на Garmin/Apple/manual).
"""

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import MagicMock, patch

from core.health.adaptive_tdee import (
    KCAL_PER_KG_FAT,
    MIN_LOGGED_DAYS,
    MIN_WEIGHT_SPAN_DAYS,
    compute_adaptive_tdee,
    get_adaptive_tdee,
)
from core.health.caloric_budget import get_daily_budget
from core.health.nutrition_targets import calculate_targets

AS_OF = date(2026, 8, 15)


def _intake(days: int, kcal: float = 2000, end: date = AS_OF) -> dict:
    """N подряд идущих полностью залогированных дней, заканчивая end."""
    return {end - timedelta(days=i): kcal for i in range(days)}


# ── compute_adaptive_tdee: чистая функция ────────────────────────────────────


def test_maintenance_on_stable_weight():
    """Вес не меняется → TDEE = средний рацион."""
    intake = _intake(30, kcal=2000)
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r is not None
    assert r["tdee"] == 2000
    assert r["days_used"] == 30


def test_deficit_weight_loss_raises_tdee_above_intake():
    """Худеет на рационе 1900 → maintenance выше рациона на 7700×скорость."""
    intake = _intake(30, kcal=1900)
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 83.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    # rate = -1.0/27 кг/день → tdee = 1900 + 7700/27 ≈ 2185
    assert r["tdee"] == round(1900 + KCAL_PER_KG_FAT / 27)


def test_surplus_weight_gain_lowers_tdee_below_intake():
    intake = _intake(30, kcal=2500)
    weights = [(AS_OF - timedelta(days=27), 83.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r["tdee"] == round(2500 - KCAL_PER_KG_FAT / 27)


def test_weight_anchors_smoothed_pm5_days():
    """Взвешивания в ±5 дней от крайних усредняются (сглаживание шума весов)."""
    intake = _intake(30, kcal=1900)
    weights = [
        (AS_OF - timedelta(days=27), 84.4),
        (AS_OF - timedelta(days=26), 83.6),  # анкер старта = (84.4+83.6)/2 = 84.0
        (AS_OF - timedelta(days=1), 83.2),
        (AS_OF, 82.8),  # анкер конца = (83.2+82.8)/2 = 83.0
    ]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r["tdee"] == round(1900 + KCAL_PER_KG_FAT / 27)


def test_not_enough_logged_days_returns_none():
    intake = _intake(MIN_LOGGED_DAYS - 1, kcal=2000)
    weights = [(AS_OF - timedelta(days=20), 84.0), (AS_OF, 84.0)]
    assert compute_adaptive_tdee(intake, weights, AS_OF) is None


def test_weight_span_too_short_returns_none():
    intake = _intake(30, kcal=2000)
    weights = [(AS_OF - timedelta(days=MIN_WEIGHT_SPAN_DAYS - 1), 84.0), (AS_OF, 84.0)]
    assert compute_adaptive_tdee(intake, weights, AS_OF) is None


def test_single_weighing_returns_none():
    intake = _intake(30, kcal=2000)
    assert compute_adaptive_tdee(intake, [(AS_OF, 84.0)], AS_OF) is None


def test_gap_days_do_not_dilute_average():
    """Дни вообще без записей — дырки в логировании, в средний рацион не входят."""
    intake = {AS_OF - timedelta(days=i): 2000 for i in range(0, 50, 2)}  # 25 дней через день
    weights = [(AS_OF - timedelta(days=40), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r is not None
    assert r["tdee"] == 2000
    assert r["days_used"] >= 21


def test_partially_logged_day_excluded():
    """День с подозрительно малым логом (< 50% медианы) — не логирован целиком."""
    intake = _intake(30, kcal=2000)
    intake[AS_OF - timedelta(days=3)] = 300  # явно неполный день
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r["tdee"] == 2000
    assert r["days_used"] == 29


def test_implausible_tdee_returns_none():
    """Мусорные данные (нереальная скорость похудения) → None, не кривая цель."""
    intake = _intake(30, kcal=1800)
    weights = [(AS_OF - timedelta(days=14), 95.0), (AS_OF, 84.0)]  # -11 кг за 2 недели
    assert compute_adaptive_tdee(intake, weights, AS_OF) is None


# ── get_adaptive_tdee: обёртка над Postgres ──────────────────────────────────


def test_get_adaptive_tdee_from_db(test_db):
    from database.crud import create_nutrition_log, create_weight

    uid = 895655
    for i in range(30):
        d = AS_OF - timedelta(days=i)
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=d,
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[{"name": "еда"}],
            totals={"calories": 1900, "protein": 100, "fats": 60, "carbs": 200},
        )
    create_weight(test_db, uid, datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc), 84.0)
    create_weight(test_db, uid, datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc), 83.0)

    r = get_adaptive_tdee(uid, as_of=AS_OF, db=test_db, stable=False)
    assert r is not None
    assert r["tdee"] == round(1900 + KCAL_PER_KG_FAT / 27)
    assert r["days_used"] == 30


def test_get_adaptive_tdee_isolated_by_user(test_db):
    """Данные другого юзера не подмешиваются (обязательный WHERE user_id)."""
    from database.crud import create_nutrition_log, create_weight

    other = 111
    for i in range(30):
        create_nutrition_log(
            db=test_db,
            user_id=other,
            date=AS_OF - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 3000},
        )
    create_weight(test_db, other, datetime(2026, 7, 19, tzinfo=timezone.utc), 90.0)
    create_weight(test_db, other, datetime(2026, 8, 15, tzinfo=timezone.utc), 90.0)

    assert get_adaptive_tdee(895655, as_of=AS_OF, db=test_db) is None


def test_weight_dates_converted_to_user_timezone(test_db):
    """Дата взвешивания — локальный день пользователя, не UTC-день (HIGH из ревью).

    21:30 UTC = 00:30 следующего дня в UTC+3: взвешивание должно лечь на
    локальную дату, иначе анкер и span сдвигаются на день.
    """
    from database.crud import create_nutrition_log, create_weight

    uid = 895655
    for i in range(30):
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=AS_OF - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 1900},
        )
    # По UTC это AS_OF-28, но в UTC+3 уже AS_OF-27
    w1 = datetime.combine(AS_OF - timedelta(days=28), time(21, 30), tzinfo=timezone.utc)
    w2 = datetime.combine(AS_OF, time(8, 0), tzinfo=timezone.utc)
    create_weight(test_db, uid, w1, 84.0)
    create_weight(test_db, uid, w2, 83.0)

    with patch("core.infra.tz.get_user_tz", return_value=timezone(timedelta(hours=3))):
        r = get_adaptive_tdee(uid, as_of=AS_OF, db=test_db, stable=False)

    assert r is not None
    assert r["span_days"] == 27
    assert r["tdee"] == round(1900 + KCAL_PER_KG_FAT / 27)


def test_smoothing_includes_weights_after_as_of(test_db):
    """Ретроспективный расчёт (/day за прошлую дату): взвешивания в ±5 дней
    ПОСЛЕ as_of тоже сглаживают конечный анкер (MEDIUM из ревью — иначе TDEE
    для одной и той же даты различался «в моменте» и задним числом)."""
    from database.crud import create_nutrition_log, create_weight

    uid = 895655
    for i in range(30):
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=AS_OF - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 1900},
        )
    create_weight(test_db, uid, datetime.combine(AS_OF - timedelta(days=27), time(8, 0), tzinfo=timezone.utc), 84.0)
    create_weight(test_db, uid, datetime.combine(AS_OF, time(8, 0), tzinfo=timezone.utc), 83.0)
    # Будущая точка в ±5 дней от конечного анкера — должна попасть в сглаживание
    create_weight(test_db, uid, datetime.combine(AS_OF + timedelta(days=3), time(8, 0), tzinfo=timezone.utc), 82.0)

    with patch("core.infra.tz.get_user_tz", return_value=timezone.utc):
        r = get_adaptive_tdee(uid, as_of=AS_OF, db=test_db, stable=False)

    # анкер конца = mean(83.0, 82.0) = 82.5 → Δ = -1.5 кг за 27 дней
    assert r["tdee"] == round(1900 + KCAL_PER_KG_FAT * 1.5 / 27)


# ── calculate_targets: адаптивный TDEE приоритетнее девайсов и manual ────────


def test_calculate_targets_adaptive_beats_stats():
    t = calculate_targets(stats={"total_calories": 1961}, user=None, adaptive_tdee=2300)
    assert t["avg_tdee"] == 2300
    assert t["calories"] == round(2300 * 0.85)


def test_calculate_targets_adaptive_beats_manual_user():
    class _User:
        bmr = 1700
        avg_active_calories = 300  # manual TDEE = 2000
        target_weight_kg = 82.0
        telegram_id = 895655

    t = calculate_targets(stats=None, user=_User(), adaptive_tdee=2300)
    assert t["avg_tdee"] == 2300


def test_calculate_targets_today_boost_applies_over_adaptive():
    """Тяжёлая тренировка: факт дня выше адаптивного → цель растёт по факту."""
    t = calculate_targets(stats=None, user=None, adaptive_tdee=2300, today_tdee=2600)
    assert t["avg_tdee"] == 2600


# ── get_daily_budget: интеграция (bmr_source='adaptive') ─────────────────────


def _fake_settings(pct=-15):
    s = MagicMock()
    s.bmr_source = "auto"
    s.bmr_override = None
    s.activity_avg_override = None
    s.calorie_goal_pct = pct
    return s


def _patched_budget(adaptive, today_tdee=None):
    avg = {"total_calories": 2151, "bmr_calories": 1771, "active_calories": 380}
    return [
        patch("database.SessionLocal", return_value=MagicMock()),
        patch("database.crud.get_user_settings", return_value=_fake_settings()),
        patch("database.crud.get_average_activity_stats", return_value=avg),
        patch("database.crud.get_activities_by_period", return_value=[]),
        patch("database.crud.get_nutrition_totals_by_date", return_value={"calories": 0}),
        patch("core.health.adaptive_tdee.get_adaptive_tdee", return_value=adaptive),
        patch("core.health.caloric_budget.get_day_actual_tdee", return_value=today_tdee),
        patch("core.health.caloric_budget.get_user_tz", return_value=timezone.utc),
    ]


def _run_budget(patches):
    for p in patches:
        p.start()
    try:
        return get_daily_budget(user_id=895655, for_date=datetime.now(timezone.utc).date())
    finally:
        for p in patches:
            p.stop()


def test_get_daily_budget_uses_adaptive_as_base():
    adaptive = {"tdee": 2300, "days_used": 40, "span_days": 27}
    b = _run_budget(_patched_budget(adaptive))
    assert b["bmr_source"] == "adaptive"
    assert b["tdee_avg"] == 2300
    assert b["target"] == round(2300 * 0.85)
    assert b["tdee_days"] == 40
    assert b["has_garmin"] is True  # цель достоверная, хинт «≈ среднее» не нужен


def test_get_daily_budget_today_boost_survives_adaptive():
    adaptive = {"tdee": 2300, "days_used": 40, "span_days": 27}
    b = _run_budget(_patched_budget(adaptive, today_tdee=2600))
    assert b["target"] == round(2600 * 0.85)
    assert b["bmr_source"] == "adaptive"


def test_get_daily_budget_adaptive_keeps_device_activity_avg():
    """activity_avg — честное девайсовое среднее, а не «адаптивный TDEE − BMR»
    (HIGH из арх-ревью: 2300−1771=529 — выдуманное число)."""
    adaptive = {"tdee": 2300, "days_used": 40, "span_days": 27}
    b = _run_budget(_patched_budget(adaptive))
    assert b["activity_avg"] == 380  # 2151 − 1771 по девайсу
    assert b["tdee_avg"] == 2300


def test_get_daily_budget_past_day_fact_clears_adaptive_label():
    """Прошедший день с полным фактом: цель от факта девайса → ярлык не
    «adaptive» и без tdee_days (HIGH из арх-ревью: противоречивая подпись
    «от факта дня · по вашим данным за N дн.»)."""
    adaptive = {"tdee": 2300, "days_used": 40, "span_days": 27}
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    patches = _patched_budget(adaptive) + [
        patch(
            "core.health.caloric_budget.get_day_energy_fact",
            return_value={"tdee": 2400.0, "bmr": 1650.0, "active": 750.0, "incomplete": False},
        ),
    ]
    for p in patches:
        p.start()
    try:
        b = get_daily_budget(user_id=895655, for_date=yesterday)
    finally:
        for p in patches:
            p.stop()
    assert b["target"] == round(2400 * 0.85)
    assert b["bmr_source"] != "adaptive"
    assert b["tdee_days"] is None


def test_get_day_stats_past_fact_clears_adaptive_source(test_db, mock_session_local):
    """/day за прошедший день с полным Garmin-фактом: подпись «по вашим
    данным» не показывается — цель посчитана от факта, не от adaptive."""
    from database.crud import create_nutrition_log, create_weight, create_or_update_activity
    from services.nutrition_service import NutritionService

    uid = 895655
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    for i in range(30):
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=yesterday - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 1900},
        )
    create_weight(test_db, uid, datetime.combine(yesterday - timedelta(days=27), time(8, 0), tzinfo=timezone.utc), 84.0)
    create_weight(test_db, uid, datetime.combine(yesterday, time(8, 0), tzinfo=timezone.utc), 83.0)
    create_or_update_activity(
        db=test_db,
        user_id=uid,
        date=yesterday,
        total_calories=2400,
        bmr_calories=1650,
        active_calories=750,
        source="garmin_connect",
    )

    with patch("core.infra.tz.get_user_tz", return_value=timezone.utc):
        stats = NutritionService(user_id=uid).get_day_stats(yesterday)

    assert stats["targets"]["calories"] == round(2400 * 0.85)
    assert stats["targets"]["tdee_source"] is None
    assert stats["targets"]["tdee_days"] is None


def test_get_daily_budget_falls_back_without_adaptive():
    b = _run_budget(_patched_budget(None))
    assert b["bmr_source"] in ("garmin", "apple_health")
    assert b["target"] == round(2151 * 0.85)
    assert b.get("tdee_days") is None


# ── get_day_stats (/day): адаптивный TDEE и подпись источника ────────────────


def test_get_day_stats_uses_adaptive(test_db, mock_session_local):
    """/day считает цель от адаптивного TDEE и отдаёт источник для подписи."""
    from database.crud import create_nutrition_log, create_weight
    from services.nutrition_service import NutritionService

    uid = 895655
    today = datetime.now(timezone.utc).date()
    # Цель считается на недельном анкере (последнее закрытое воскресенье) —
    # ровный ряд 80 дней, вес −1 кг каждые 27 дней: сырой TDEE на всех анкерах одинаков.
    for i in range(80):
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=today - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 1900},
        )
    for i in range(0, 81, 3):
        t = datetime.combine(today - timedelta(days=i), time(8, 0), tzinfo=timezone.utc)
        create_weight(test_db, uid, t, 83.0 + i / 27)

    with patch("core.infra.tz.get_user_tz", return_value=timezone.utc):
        stats = NutritionService(user_id=uid).get_day_stats(today)

    expected_tdee = round(1900 + KCAL_PER_KG_FAT / 27)
    assert stats["targets"]["tdee_source"] == "adaptive"
    assert stats["targets"]["tdee_days"] == 42
    assert stats["targets"]["avg_tdee"] == expected_tdee
    assert stats["targets"]["calories"] == round(expected_tdee * 0.85)


# ── compute_goals (миниапп): прокидывание источника ──────────────────────────


def test_compute_goals_passes_adaptive_source():
    from webhook.nutrition_goals import compute_goals

    budget = {
        "target": 1955,
        "bmr_avg": 1771,
        "activity_avg": 529,
        "tdee_avg": 2300,
        "bmr_source": "adaptive",
        "tdee_days": 40,
        "calorie_goal_pct": -15,
        "data_incomplete": False,
    }
    with patch("webhook.nutrition_goals.get_daily_budget", return_value=budget):
        g = compute_goals(user_id=895655)
    assert g["tdee_source"] == "adaptive"
    assert g["tdee_days"] == 40


# ── Защита от недолога (15.11.2026, ADR-0015) ────────────────────────────────


def test_day_below_70pct_of_median_excluded():
    """Порог неполного дня 0.7: день с забытым рестораном (1300 при медиане 2000) не в среднем."""
    intake = _intake(30, kcal=2000)
    intake[AS_OF - timedelta(days=5)] = 1300
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r["tdee"] == 2000
    assert r["excluded_days"] == 1


def test_user_flag_incomplete_excludes_day_above_threshold():
    """«Что-то пропустил» исключает день, даже если эвристика сочла бы его полным."""
    intake = _intake(30, kcal=2000)
    intake[AS_OF - timedelta(days=5)] = 1700
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF, day_status={AS_OF - timedelta(days=5): False})
    assert r["tdee"] == 2000
    assert r["days_used"] == 29


def test_user_flag_complete_keeps_light_day():
    """«Да, всё» оставляет лёгкий день (1000 ккал) в среднем — пользователю виднее."""
    intake = _intake(30, kcal=2000)
    light = AS_OF - timedelta(days=5)
    intake[light] = 1000
    weights = [(AS_OF - timedelta(days=27), 84.0), (AS_OF, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF, day_status={light: True})
    assert r["days_used"] == 30
    assert r["avg_intake"] == round((29 * 2000 + 1000) / 30)


def test_stale_weight_freezes_estimate():
    """Взвешиваний нет 10 дней — расчёт замораживается на последнем замере + 3 дня,
    и поздний недолог (дни по 1000 ккал без отметок) в него не попадает."""
    last_w = AS_OF - timedelta(days=10)
    intake = _intake(50, kcal=2000)
    for i in range(7):
        intake[AS_OF - timedelta(days=i)] = 1500
    weights = [(last_w - timedelta(days=27), 84.0), (last_w, 84.0)]
    r = compute_adaptive_tdee(intake, weights, AS_OF)
    assert r["frozen"] is True
    assert r["as_of_effective"] == last_w + timedelta(days=3)
    assert r["tdee"] == 2000


def test_no_weighing_before_as_of_returns_none():
    intake = _intake(30)
    assert compute_adaptive_tdee(intake, [(AS_OF + timedelta(days=1), 80.0)], AS_OF) is None


def _steady(days: int, kcal: float, end: date):
    return {end - timedelta(days=i): kcal for i in range(days)}


def test_stable_uses_last_closed_sunday():
    """Цель стабильна всю неделю: анкер — воскресенье перед as_of."""
    from core.health.adaptive_tdee import compute_stable_adaptive_tdee, stable_anchor

    assert AS_OF.weekday() == 5  # суббота
    assert stable_anchor(AS_OF) == date(2026, 8, 9)
    assert stable_anchor(date(2026, 8, 10)) == date(2026, 8, 9)  # понедельник
    intake = _steady(90, 2000, AS_OF)
    weights = [(AS_OF - timedelta(days=i), 84.0) for i in range(0, 90, 3)]
    r = compute_stable_adaptive_tdee(intake, weights, AS_OF)
    assert r["anchor"] == date(2026, 8, 9)
    assert r["tdee"] == 2000


def test_stable_caps_weekly_drop_at_100():
    """Резкий провал сырой оценки (недолог последних недель) опускает цель не больше чем на 100/нед."""
    from core.health.adaptive_tdee import MAX_WEEKLY_STEP_KCAL, compute_stable_adaptive_tdee

    intake = _steady(120, 2200, AS_OF)
    for i in range(14):  # две последние недели — сплошной недолог, но выше порога 0.7
        intake[AS_OF - timedelta(days=i)] = 1600
    weights = [(AS_OF - timedelta(days=i), 84.0) for i in range(0, 120, 2)]
    r = compute_stable_adaptive_tdee(intake, weights, AS_OF)
    assert r["raw_tdee"] < 2200 - MAX_WEEKLY_STEP_KCAL
    assert r["tdee"] >= 2200 - MAX_WEEKLY_STEP_KCAL * 2


def test_stable_floor_bmr_x_1_2():
    from core.health.adaptive_tdee import compute_stable_adaptive_tdee

    intake = _steady(120, 1500, AS_OF)
    weights = [(AS_OF - timedelta(days=i), 84.0) for i in range(0, 120, 2)]
    r = compute_stable_adaptive_tdee(intake, weights, AS_OF, bmr=1600)
    assert r["floored"] is True
    assert r["tdee"] == 1920
    r2 = compute_stable_adaptive_tdee(intake, weights, AS_OF, bmr=None)
    assert r2["floored"] is False
    assert r2["tdee"] == 1500


def test_mifflin_bmr():
    from core.health.adaptive_tdee import mifflin_bmr

    assert mifflin_bmr("male", 77, 170, 49) == 1592
    assert mifflin_bmr("female", 60, 165, 40) == round(600 + 1031.25 - 200 - 161)
    assert mifflin_bmr(None, 77, 170, 49) is None


def test_get_adaptive_tdee_reads_day_status_and_profile_floor(test_db):
    """Обвязка: отметки дня из БД исключают день, пол берётся из профиля (Миффлин)."""
    from database.crud import create_nutrition_log, create_weight, set_day_status
    from database.models import User

    uid = 895655
    user = test_db.query(User).filter(User.telegram_id == uid).first()
    if user is None:
        user = User(telegram_id=uid, first_name="T")
        test_db.add(user)
    user.birth_date = date(1977, 5, 15)
    user.height_cm = 170
    user.sex = "male"
    test_db.commit()

    for i in range(120):
        create_nutrition_log(
            db=test_db,
            user_id=uid,
            date=AS_OF - timedelta(days=i),
            meal_time=time(12, 0),
            meal_name="lunch",
            items=[],
            totals={"calories": 1500},
        )
    for i in range(0, 120, 3):
        create_weight(test_db, uid, datetime.combine(AS_OF - timedelta(days=i), time(8, 0), tzinfo=timezone.utc), 77.0)
    set_day_status(test_db, uid, AS_OF - timedelta(days=10), False, source="morning_check")

    with patch("core.infra.tz.get_user_tz", return_value=timezone.utc):
        raw = get_adaptive_tdee(uid, as_of=AS_OF, db=test_db, stable=False)
        r = get_adaptive_tdee(uid, as_of=AS_OF, db=test_db)

    assert raw["excluded_days"] == 1
    assert r["floored"] is True
    assert r["tdee"] == round(1592 * 1.2)


def test_set_day_status_upserts(test_db):
    from database.crud import get_day_statuses_by_period, set_day_status
    from database.models import User

    uid = 895655
    if test_db.query(User).filter(User.telegram_id == uid).first() is None:
        test_db.add(User(telegram_id=uid, first_name="T"))
        test_db.commit()
    d = date(2026, 11, 14)
    set_day_status(test_db, uid, d, False)
    set_day_status(test_db, uid, d, True, source="agent")
    assert get_day_statuses_by_period(test_db, uid, d, d) == {d: True}
