"""Свёртка почасовых рядов Garmin для get_intraday_timeline."""

from datetime import datetime, timedelta, timezone

from core.health.intraday import build_timeline

# Синтетический день в UTC+4: спокойное утро, стресс ~70 с 10:30,
# часы сняты 13:30–14:30, вечером снова высокий стресс.
_DAY_START_UTC = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)  # 00:00 местного


def _stress_at(local_min: int) -> int:
    if 13 * 60 + 30 <= local_min < 14 * 60 + 30:
        return -2
    if 10 * 60 + 30 <= local_min < 13 * 60 + 30 or 18 * 60 <= local_min < 20 * 60:
        return 72
    return 15


def _payload():
    stress, bb = [], []
    for i in range(0, 24 * 60, 3):
        ts = int((_DAY_START_UTC + timedelta(minutes=i)).timestamp() * 1000)
        stress.append([ts, _stress_at(i)])
        bb.append([ts, "MEASURED", max(5, 70 - i // 25), 3.0])
    return {
        "startTimestampGMT": "2026-10-30T20:00:00.0",
        "startTimestampLocal": "2026-10-31T00:00:00.0",
        "avgStressLevel": 35,
        "maxStressLevel": 72,
        "stressValuesArray": stress,
        "bodyBatteryValuesArray": bb,
    }


def _by_time(result):
    return {row["time"]: row for row in result["timeline"]}


def test_uses_device_offset_not_profile_tz():
    # Часы были в UTC+4; профильная таймзона другая — верим устройству.
    result = build_timeline(_payload(), None, fallback_offset=timedelta(hours=3))
    assert result["device_utc_offset_hours"] == 4


def test_stress_rise_visible_before_noon():
    rows = _by_time(build_timeline(_payload(), None, timedelta(hours=4)))
    assert rows["08:00"]["stress_avg"] < 25
    assert rows["11:00"]["stress_avg"] > 60


def test_marks_gap_when_watch_off():
    rows = _by_time(build_timeline(_payload(), None, timedelta(hours=4)))
    assert "stress_avg" not in rows["13:30"]
    assert "note" in rows["13:30"]


def test_high_stress_episodes_have_local_times():
    result = build_timeline(_payload(), None, timedelta(hours=4))
    starts = [e["from"] for e in result["high_stress_episodes"]]
    assert starts and all(len(s) == 5 for s in starts)
    assert any(s < "12:00" for s in starts)


def test_body_battery_and_heart_rate_buckets():
    hr = {
        "startTimestampGMT": "2026-10-30T20:00:00.0",
        "startTimestampLocal": "2026-10-31T00:00:00.0",
        "restingHeartRate": 51,
        "heartRateValues": [
            [int((_DAY_START_UTC + timedelta(hours=9, minutes=40)).timestamp() * 1000), 86],
            [int((_DAY_START_UTC + timedelta(hours=9, minutes=42)).timestamp() * 1000), 98],
            [int((_DAY_START_UTC + timedelta(hours=9, minutes=44)).timestamp() * 1000), None],
        ],
    }
    result = build_timeline(_payload(), hr, timedelta(hours=4))
    rows = _by_time(result)
    assert rows["09:30"]["hr_max"] == 98
    assert "→" in rows["08:00"]["body_battery"]
    assert result["resting_hr"] == 51
