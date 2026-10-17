"""Тесты вкладки «Состояние»: сервис services/health_summary.py и GET /api/health/summary."""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.models import (
    ActivityLog,
    BloodPressureLog,
    BloodTest,
    GlucoseReading,
    User,
    Weight,
    Workout,
)
from services import health_summary as hs

UID = 777
TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def _user(db, sex=None, uid=UID):
    db.add(User(telegram_id=uid, first_name="T", onboarding_data={"sex": sex} if sex else {}))
    db.commit()


def _act(db, d, uid=UID, **kw):
    kw.setdefault("source", "garmin_sleep")
    db.add(ActivityLog(user_id=uid, date=d, **kw))


def _days(n, end=TODAY):
    """n дат по возрастанию, последняя — end."""
    return [end - timedelta(days=n - 1 - i) for i in range(n)]


def _seed_sleep(db, recent, base, uid=UID):
    """recent — значения за 7 ночей (до сегодня включительно), base — за 14 ночей до окна."""
    for d, v in zip(_days(len(recent)), recent):
        _act(db, d, uid, sleep_hours=v)
    for d, v in zip(_days(len(base), TODAY - timedelta(days=7)), base):
        _act(db, d, uid, sleep_hours=v)
    db.commit()


def _build(db, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("now", NOW)
    return hs.build_health_summary(db, UID, **kw)


def _ids(s):
    return [a.id for a in s.attention]


# ── Нет пользователя / нет потоков ────────────────────────────────────────────


def test_no_user_is_onboarding(test_db):
    s = _build(test_db)
    assert s.onboarding is True and s.streams == {} and s.attention == []


def test_user_without_data_has_no_streams_only_gaps(test_db):
    _user(test_db)
    s = _build(test_db)
    assert s.streams == {}  # контракт: не подключённые потоки — без ключа
    assert {g.stream for g in s.data_gaps} == set(hs.STREAM_ORDER)
    assert all(g.reason == "not_connected" for g in s.data_gaps)
    assert s.attention == []
    assert "Недостаточно данных" in s.summary_text  # пустой attention ≠ «всё хорошо»


# ── Сон: S1 ────────────────────────────────────────────────────────────────────


def test_sleep_relative_drop_triggers_medium(test_db):
    _user(test_db)
    _seed_sleep(test_db, [6.1] * 7, [7.2] * 14)  # 6.1 ≤ 7.2 − 1.0, но не <6.0
    s = _build(test_db)
    it = s.attention[0]
    assert it.id == "sleep_low_7d" and it.severity == "medium"
    assert it.evidence.recent["n"] == 7 and it.evidence.recent["kind"] == "mean"
    assert it.evidence.baseline["kind"] == "median" and it.evidence.baseline["n"] == 14
    assert s.streams["sleep"].status == "attention"


def test_sleep_boundary_exactly_minus_one_hour_triggers_and_just_above_does_not(test_db):
    _user(test_db)
    _seed_sleep(test_db, [6.2] * 7, [7.2] * 14)  # ровно −1.0 → срабатывает
    assert "sleep_low_7d" in _ids(_build(test_db))
    test_db.query(ActivityLog).delete()
    test_db.commit()
    _seed_sleep(test_db, [6.3] * 7, [7.2] * 14)  # −0.9 → нет
    assert _ids(_build(test_db)) == []


def test_sleep_absolute_threshold_is_strictly_below_six(test_db):
    _user(test_db)
    _seed_sleep(test_db, [6.0] * 7, [6.0] * 14)  # ровно 6.0 и без падения → нет
    assert _ids(_build(test_db)) == []


def test_sleep_both_conditions_and_three_short_nights_is_high(test_db):
    _user(test_db)
    _seed_sleep(test_db, [5.0] * 7, [7.5] * 14)
    assert _build(test_db).attention[0].severity == "high"


def test_sleep_too_few_points_is_insufficient_and_not_compared(test_db):
    _user(test_db)
    _seed_sleep(test_db, [4.0] * 3, [7.5] * 14)  # N=3 <4
    s = _build(test_db)
    assert s.attention == []
    c = s.streams["sleep"]
    assert c.status == "insufficient" and c.avg.n == 3
    assert any(g.stream == "sleep" and g.reason == "insufficient" and g.n == 3 for g in s.data_gaps)


def test_sleep_short_baseline_only_absolute_rule_applies(test_db):
    _user(test_db)
    _seed_sleep(test_db, [5.5] * 7, [7.5] * 6)  # baseline N=6 <7 → baseline=None
    s = _build(test_db)
    assert s.streams["sleep"].baseline is None
    assert s.attention[0].id == "sleep_low_7d"
    assert "норма" not in s.attention[0].detail


def test_sleep_today_night_counts_and_series_has_exactly_window_points(test_db):
    _user(test_db)
    _seed_sleep(test_db, [7.0] * 6 + [4.0], [7.0] * 14)  # сегодняшняя ночь — 4.0 ч
    c = _build(test_db).streams["sleep"]
    assert c.latest.date == TODAY.isoformat() and c.latest.value == 4.0
    assert len(c.series) == 7 and c.series[-1].date == TODAY.isoformat()


def test_sleep_stale_when_no_rows_in_window(test_db):
    _user(test_db)
    _act(test_db, TODAY - timedelta(days=20), sleep_hours=7.0)
    test_db.commit()
    c = _build(test_db).streams["sleep"]
    assert c.status == "stale" and c.stale_days == 20 and c.latest.value == 7.0
    assert c.avg is None


# ── Активность: A1, неполный сегодняшний день ─────────────────────────────────


def test_today_steps_are_ignored(test_db):
    _user(test_db)
    for d in _days(7, TODAY - timedelta(days=1)):
        _act(test_db, d, steps=8000)
    _act(test_db, TODAY, steps=50)  # неполный день
    test_db.commit()
    c = _build(test_db).streams["activity"]
    assert c.avg.value == 8000 and c.avg.n == 7
    assert c.latest.date == (TODAY - timedelta(days=1)).isoformat()
    assert c.series[-1].date == (TODAY - timedelta(days=1)).isoformat()


def test_steps_drop_is_info(test_db):
    _user(test_db)
    for d in _days(7, TODAY - timedelta(days=1)):
        _act(test_db, d, steps=5000)
    for d in _days(14, TODAY - timedelta(days=8)):
        _act(test_db, d, steps=8000)
    test_db.commit()  # 5000 ≤ 0.7 × 8000 = 5600
    it = _build(test_db).attention[0]
    assert it.id == "steps_low_7d" and it.severity == "info"


def test_short_workouts_not_counted_and_no_workouts_rule(test_db):
    _user(test_db)
    for i in range(7):
        _act(test_db, TODAY - timedelta(days=1 + i), steps=7000)
    for i in range(3):  # 3 настоящие тренировки в предыдущие 4 недели
        test_db.add(
            Workout(
                user_id=UID,
                date=TODAY - timedelta(days=12 + i),
                duration_minutes=40,
                start_time=NOW - timedelta(days=12 + i),
            )
        )
    test_db.add(
        Workout(user_id=UID, date=TODAY - timedelta(days=2), duration_minutes=9, start_time=NOW - timedelta(days=2))
    )  # <10 мин — не тренировка
    test_db.commit()
    s = _build(test_db)
    assert s.streams["activity"].extra["workouts"]["count"] == 0
    assert "workouts_none_7d" in _ids(s)


def test_workouts_rule_needs_history(test_db):
    _user(test_db)
    for i in range(7):
        _act(test_db, TODAY - timedelta(days=1 + i), steps=7000)
    for i in range(2):  # только 2 в истории
        test_db.add(
            Workout(
                user_id=UID,
                date=TODAY - timedelta(days=12 + i),
                duration_minutes=40,
                start_time=NOW - timedelta(days=12 + i),
            )
        )
    test_db.commit()
    assert "workouts_none_7d" not in _ids(_build(test_db))


# ── HRV / пульс: H1, H2, семейство источников ────────────────────────────────


def _seed_hrv(db, recent, base, recent_src="garmin_hrv", base_src="garmin_hrv"):
    for d, v in zip(_days(len(recent)), recent):
        _act(db, d, hrv=v, source=recent_src)
    for d, v in zip(_days(len(base), TODAY - timedelta(days=7)), base):
        _act(db, d, hrv=v, source=base_src)
    db.commit()


def test_hrv_drop_within_same_family_triggers(test_db):
    _user(test_db)
    _seed_hrv(test_db, [42] * 7, [50] * 14)  # 42 ≤ 0.85 × 50 = 42.5
    s = _build(test_db)
    assert "hrv_low_7d" in _ids(s) and s.streams["hrv"].extra["source"] == "garmin"


def test_hrv_boundary_just_above_does_not_trigger(test_db):
    _user(test_db)
    _seed_hrv(test_db, [43] * 7, [50] * 14)  # 43 > 42.5
    assert _ids(_build(test_db)) == []


def test_hrv_baseline_from_other_family_is_not_comparable(test_db):
    _user(test_db)
    _seed_hrv(test_db, [30] * 7, [60] * 14, recent_src="apple_health", base_src="garmin_hrv")
    s = _build(test_db)
    assert s.streams["hrv"].baseline is None  # Apple SDNN против Garmin lastNightAvg не сравниваем
    assert _ids(s) == []


def test_resting_hr_rise_is_medium_and_mixed_is_info(test_db):
    _user(test_db)
    for d in _days(7, TODAY - timedelta(days=1)):
        _act(test_db, d, heart_rate_avg=66, source="apple_health", raw_data={"resting_heart_rate": 66})
    for d in _days(14, TODAY - timedelta(days=8)):
        _act(test_db, d, heart_rate_avg=60, source="apple_health", raw_data={"resting_heart_rate": 60})
    test_db.commit()
    it = [a for a in _build(test_db).attention if a.id == "hr_high_7d"][0]
    assert it.severity == "medium" and it.evidence.extra["kind"] == "resting"
    test_db.query(ActivityLog).update({ActivityLog.raw_data: None})  # семантика пульса неизвестна → «mixed» → info
    test_db.commit()
    it = [a for a in _build(test_db).attention if a.id == "hr_high_7d"][0]
    assert it.severity == "info"


# ── Давление: B1, B2 ───────────────────────────────────────────────────────────


def _bp(db, days_ago, sys_, dia):
    db.add(BloodPressureLog(user_id=UID, measured_at=NOW - timedelta(days=days_ago), systolic=sys_, diastolic=dia))


def test_bp_two_high_readings_is_high_and_placeholders_dropped(test_db):
    _user(test_db)
    _bp(test_db, 1, 145, 92)
    _bp(test_db, 3, 141, 85)
    _bp(test_db, 5, 120, 78)
    _bp(test_db, 6, 0, 0)  # заглушка — отбрасывается
    test_db.commit()
    s = _build(test_db)
    c = s.streams["bp"]
    assert c.extra["n"] == 3 and c.extra["count_ge_140_90"] == 2
    assert s.attention[0].id == "bp_high_14d" and s.attention[0].severity == "high"


def test_bp_avg_stage1_is_medium_and_one_high_reading_is_not_b1(test_db):
    _user(test_db)
    _bp(test_db, 1, 131, 79)
    _bp(test_db, 2, 130, 80)
    _bp(test_db, 3, 129, 81)
    test_db.commit()
    s = _build(test_db)
    assert [a.id for a in s.attention] == ["bp_avg_14d"] and s.attention[0].severity == "medium"


def test_bp_boundary_below_stage1_and_too_few_points(test_db):
    _user(test_db)
    for i, (a, b) in enumerate([(129, 79), (129, 79), (129, 79)]):
        _bp(test_db, i + 1, a, b)
    test_db.commit()
    assert _ids(_build(test_db)) == []
    test_db.query(BloodPressureLog).delete()
    _bp(test_db, 1, 170, 100)
    _bp(test_db, 2, 170, 100)  # N=2 <3 → не сравниваем
    test_db.commit()
    s = _build(test_db)
    assert s.attention == [] and s.streams["bp"].status == "insufficient"


# ── Глюкоза: G1 ────────────────────────────────────────────────────────────────


def _cgm(db, n, value_fn, days=7):
    step = timedelta(days=days) / n
    for i in range(n):
        db.add(GlucoseReading(user_id=UID, ts=NOW - timedelta(minutes=1) - step * i, value=value_fn(i)))
    db.commit()


def test_glucose_low_coverage_is_insufficient(test_db):
    _user(test_db)
    _cgm(test_db, 600, lambda i: 13.0)  # 600 < 0.7 × 2016
    s = _build(test_db)
    assert s.attention == [] and s.streams["glucose"].status == "insufficient"


def test_glucose_low_tir_and_high_tbr_trigger(test_db):
    _user(test_db)
    _cgm(test_db, 2000, lambda i: 3.5 if i % 10 == 0 else (12.0 if i % 10 < 4 else 6.0))  # TBR 10 %, TIR ~60 %
    s = _build(test_db)
    assert {"glucose_tir_low", "glucose_tbr_high"} <= set(_ids(s))
    assert s.streams["glucose"].extra["tbr_pct"] == 10.0


def test_glucose_good_values_no_attention(test_db):
    _user(test_db)
    _cgm(test_db, 2000, lambda i: 5.5)
    s = _build(test_db)
    assert s.attention == [] and s.streams["glucose"].status == "ok"


# ── Вес: W1, stale ───────────────────────────────────────────────────────────


def _w(db, days_ago, kg, fat=None):
    db.add(Weight(user_id=UID, measured_at=NOW - timedelta(days=days_ago), weight=kg, body_fat=fat))


def test_weight_stale_has_stale_days(test_db):
    _user(test_db)
    _w(test_db, 40, 82.0, fat=21.0)
    test_db.commit()
    c = _build(test_db).streams["weight"]
    assert c.status == "stale" and c.stale_days == 40
    assert c.latest.value == 82.0 and c.latest.date == (TODAY - timedelta(days=40)).isoformat()


def test_weight_change_uses_first_and_last_measurement(test_db):
    _user(test_db)
    _w(test_db, 12, 85.0)
    _w(test_db, 6, 84.0)
    _w(test_db, 1, 82.4)  # −3.06 % по первому и последнему
    test_db.commit()
    s = _build(test_db)
    assert s.attention[0].id == "weight_change_14d" and s.attention[0].severity == "info"


def test_weight_change_needs_gap_of_seven_days_and_three_percent(test_db):
    _user(test_db)
    _w(test_db, 8, 85.0)
    _w(test_db, 3, 80.0)  # промежуток 5 дн. <7 → нет
    test_db.commit()
    assert _ids(_build(test_db)) == []
    test_db.query(Weight).delete()
    _w(test_db, 12, 85.0)
    _w(test_db, 1, 82.6)  # −2.8 % <3 → нет
    test_db.commit()
    assert _ids(_build(test_db)) == []


# ── Анализы: L1–L3, пол ───────────────────────────────────────────────────────


def _test(db, d, **vals):
    db.add(BloodTest(user_id=UID, test_date=d, test_type="blood", values=vals, status="current"))
    db.commit()


def test_labs_male_flags_history_and_l3_escalation(test_db):
    _user(test_db, sex="male")
    d0 = TODAY - timedelta(days=200)
    _test(test_db, d0, LDL=3.2)
    _test(test_db, TODAY - timedelta(days=30), LDL=3.9)
    s = _build(test_db)
    lab = s.streams["labs"]
    ldl = [o for o in lab.out_of_range if o.key == "LDL"][0]
    assert ldl.direction == "high" and ldl.flag == "↑" and ldl.deviation_pct == 30
    assert [h["value"] for h in ldl.history] == [3.2, 3.9]
    assert ldl.severity == "high"  # приоритетный маркер, >25 %, плюс ухудшение
    assert s.attention[0].id == "lab_LDL" and "Обсудить" in s.attention[0].action
    assert lab.status == "attention" and lab.ref_note


def test_labs_just_inside_range_is_not_flagged_and_medium_when_small_deviation(test_db):
    _user(test_db, sex="male")
    _test(test_db, TODAY - timedelta(days=10), LDL=3.0, HDL=0.9)  # LDL ровно в границе; HDL ниже 1.0 на 10 %
    lab = _build(test_db).streams["labs"]
    assert [o.key for o in lab.out_of_range] == ["HDL"]
    assert lab.out_of_range[0].severity == "medium"


def test_labs_without_explicit_sex_show_values_but_no_flags(test_db):
    _user(test_db)  # onboarding_data без пола; users.sex остался дефолтным 'male'
    _test(test_db, TODAY - timedelta(days=10), LDL=5.0)
    s = _build(test_db)
    lab = s.streams["labs"]
    assert s.sex is None and lab.out_of_range == []
    m = lab.markers[0]
    assert m.key == "LDL" and m.value == 5.0 and m.flag == "" and m.ref_high is None
    assert [a for a in s.attention if a.stream == "labs" and a.id != "labs_stale"] == []
    assert any(g.reason == "sex_not_set" for g in s.data_gaps)


def test_labs_female_gets_no_flags(test_db):
    _user(test_db, sex="female")
    _test(test_db, TODAY - timedelta(days=10), LDL=5.0)
    s = _build(test_db)
    assert s.sex == "female" and s.streams["labs"].out_of_range == []
    assert "мужчин" in s.streams["labs"].ref_note


def test_labs_stale_marker_goes_to_one_info_item_without_flag(test_db):
    _user(test_db, sex="male")
    _test(test_db, TODAY - timedelta(days=800), LDL=5.0, vitamin_D=10)  # LDL порог 730, D порог 365
    s = _build(test_db)
    lab = s.streams["labs"]
    assert {x.key for x in lab.stale} == {"LDL", "vitamin_D"}
    assert lab.out_of_range == []  # просроченное значение не флагуем, а просим пересдать
    assert [a.id for a in s.attention] == ["labs_stale"] and s.attention[0].severity == "info"
    assert "Просрочены анализы: 2" in s.summary_text


# ── Ранжирование ─────────────────────────────────────────────────────────────


def test_attention_ranked_by_severity_then_freshness_and_capped(test_db):
    def mk(i, sev, d):
        return hs.AttentionItem(
            id=i, stream="sleep", severity=sev, title="t", detail="d", evidence=hs.Evidence(metric="m"), data_date=d
        )

    items = [
        mk("a", "info", "2026-10-17"),
        mk("b", "medium", "2026-10-10"),
        mk("c", "medium", "2026-10-16"),
        mk("d", "high", "2026-10-01"),
        mk("e", "info", "2026-10-16"),
    ]
    ranked = hs.rank_attention(items)
    assert [i.id for i in ranked] == ["d", "c", "b", "a"]  # high, затем medium по свежести; максимум 4


def test_schema_has_no_correlation_fields(test_db):
    _user(test_db)
    _seed_sleep(test_db, [5.0] * 7, [7.5] * 14)
    dumped = _build(test_db).model_dump(mode="json")
    assert "correlation" not in str(dumped).lower()


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_db():
    """In-memory SQLite со StaticPool — безопасно для TestClient (другой поток)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database.models import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api(api_db, monkeypatch):
    import database
    from webhook import health_summary_api
    from webhook.tg_auth import get_tg_user

    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: api_db)
    app = FastAPI()
    app.include_router(health_summary_api.router)
    state = {"user": {"id": UID}}
    app.dependency_overrides[get_tg_user] = lambda: state["user"]
    client = TestClient(app)
    client.state = state
    return client


def test_api_no_user_row_returns_onboarding(api):
    r = api.get("/api/health/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["onboarding"] is True and body["streams"] == {} and body["attention"] == []


def test_api_missing_id_is_400(api):
    api.state["user"] = {}
    assert api.get("/api/health/summary").status_code == 400


def test_api_returns_summary_with_contract_fields(api, api_db):
    test_db = api_db
    _user(test_db, sex="male")
    today = datetime.now(timezone.utc).date()
    for i in range(7):
        test_db.add(ActivityLog(user_id=UID, date=today - timedelta(days=i), sleep_hours=5.0, source="garmin_sleep"))
    for i in range(14):
        test_db.add(
            ActivityLog(user_id=UID, date=today - timedelta(days=7 + i), sleep_hours=7.5, source="garmin_sleep")
        )
    test_db.commit()
    r = api.get("/api/health/summary?days=7&lang=en")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {
        "as_of",
        "tz",
        "window_days",
        "sex",
        "attention",
        "summary_text",
        "streams",
        "data_gaps",
        "links",
    }
    assert body["lang"] == "en" and body["sex"] == "male"
    assert list(body["streams"]) == ["sleep"]  # остальные не подключены → нет ключа
    assert body["attention"][0]["id"] == "sleep_low_7d" and body["attention"][0]["title"] == "Sleep shorter than usual"
    assert body["streams"]["sleep"]["avg"]["kind"] == "mean"
    assert {g["stream"] for g in body["data_gaps"]} == {"activity", "hrv", "weight", "bp", "glucose", "labs"}


def test_api_rejects_out_of_range_days(api):
    assert api.get("/api/health/summary?days=3").status_code == 422
    assert api.get("/api/health/summary?days=60").status_code == 422
