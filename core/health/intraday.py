"""Внутридневная хронология пульса, стресса и Body Battery.

Зачем: суточные итоги (средний стресс, HRV за ночь, min/max Body Battery) не
отвечают на вопросы «когда это началось?», «стресс вырос до или после купания?».
Прецедент 01.11.2026: агент на такой вопрос рассуждал о вчерашнем ужине, потому
что почасовых данных у него не было, хотя они лежат в Garmin.

Источники по приоритету:
1. Garmin Connect по garth-токенам пользователя (`/app/data/garth/<uid>/`) —
   стресс + Body Battery + пульс, свежие.
2. Локальные файлы Garmin-синка владельца (`data/garmin/stress/<date>.json`) —
   только стресс + Body Battery, без пульса.

Время ведётся по часам устройства (startTimestampLocal − startTimestampGMT),
а не по таймзоне профиля: человек мог уехать, часы перевели время сами.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_GARTH_HOME = os.getenv("GARTH_HOME", "/app/data/garth")
_GARMIN_FILES = Path(os.getenv("GARMIN_DATA_DIR", "/app/data/garmin"))

BUCKET_MIN = 30
# Garmin помечает интервалы без оценки стресса отрицательными значениями:
# -1 — движение/активность, -2 — мало данных (часы сняты, вода).
_STRESS_ACTIVE = -1
HIGH_STRESS = 60
MIN_EPISODE_MIN = 30


def _garmin_client(user_id: int):
    garth_dir = os.path.join(_GARTH_HOME, str(user_id))
    if not os.path.exists(os.path.join(garth_dir, "oauth1_token.json")):
        return None
    try:
        import warnings

        import garth
        from garminconnect import Garmin

        warnings.filterwarnings("ignore", category=DeprecationWarning)
        garth.resume(garth_dir)
        client = Garmin()
        client.login(garth_dir)
        return client
    except Exception as e:
        logger.warning("intraday: Garmin token auth failed for %s: %s", user_id, e)
        return None


def _device_offset(payload: dict) -> Optional[timedelta]:
    try:
        local = datetime.fromisoformat(payload["startTimestampLocal"].split(".")[0])
        gmt = datetime.fromisoformat(payload["startTimestampGMT"].split(".")[0])
        return local - gmt
    except Exception:
        return None


def _fetch(user_id: int, day: str, primary_id: int) -> tuple[Optional[dict], Optional[dict], str]:
    """(stress_payload, hr_payload, source)."""
    client = _garmin_client(user_id)
    if client is not None:
        try:
            stress = client.get_stress_data(day)
            try:
                hr = client.get_heart_rates(day)
            except Exception as e:
                logger.warning("intraday: get_heart_rates failed: %s", e)
                hr = None
            if stress and stress.get("stressValuesArray"):
                return stress, hr, "garmin_api"
        except Exception as e:
            logger.warning("intraday: get_stress_data failed for %s %s: %s", user_id, day, e)

    if user_id == primary_id:
        path = _GARMIN_FILES / "stress" / f"{day}.json"
        if path.exists():
            try:
                return json.loads(path.read_text()), None, "garmin_files"
            except Exception as e:
                logger.warning("intraday: bad file %s: %s", path, e)
    return None, None, "none"


def _bucket_key(ts_ms: int, offset: timedelta) -> str:
    t = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None) + offset
    minute = (t.minute // BUCKET_MIN) * BUCKET_MIN
    return f"{t.hour:02d}:{minute:02d}"


def _local_hhmm(ts_ms: int, offset: timedelta) -> str:
    t = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None) + offset
    return t.strftime("%H:%M")


def build_timeline(stress_payload: dict, hr_payload: Optional[dict], fallback_offset: timedelta) -> dict:
    """Свернуть сырые ряды Garmin в получасовые корзины + эпизоды высокого стресса."""
    offset = _device_offset(stress_payload)
    if offset is None and hr_payload:
        offset = _device_offset(hr_payload)
    if offset is None:
        offset = fallback_offset

    buckets: dict[str, dict] = {}

    def b(key: str) -> dict:
        return buckets.setdefault(key, {"stress": [], "active": 0, "no_data": 0, "bb": [], "hr": []})

    stress_rows = [r for r in (stress_payload.get("stressValuesArray") or []) if r and r[1] is not None]
    for ts, val in stress_rows:
        cell = b(_bucket_key(ts, offset))
        if val >= 0:
            cell["stress"].append(val)
        elif val == _STRESS_ACTIVE:
            cell["active"] += 1
        else:
            cell["no_data"] += 1

    for row in stress_payload.get("bodyBatteryValuesArray") or []:
        # [ts, status, level, version] (v2) или [ts, level] (старый формат)
        level = row[2] if len(row) >= 3 else row[1]
        if isinstance(level, (int, float)):
            b(_bucket_key(row[0], offset))["bb"].append(int(level))

    if hr_payload:
        for ts, val in hr_payload.get("heartRateValues") or []:
            if val:
                b(_bucket_key(ts, offset))["hr"].append(val)

    timeline = []
    for key in sorted(buckets):
        c = buckets[key]
        item: dict = {"time": key}
        if c["hr"]:
            item["hr_avg"] = round(sum(c["hr"]) / len(c["hr"]))
            item["hr_max"] = max(c["hr"])
        if c["stress"]:
            item["stress_avg"] = round(sum(c["stress"]) / len(c["stress"]))
            item["stress_max"] = max(c["stress"])
        if c["bb"]:
            item["body_battery"] = f"{c['bb'][0]}→{c['bb'][-1]}"
        if c["active"] and c["active"] >= len(c["stress"]):
            item["note"] = "движение/активность (стресс не считается)"
        elif c["no_data"] and not c["stress"]:
            item["note"] = "пропуск: часы сняты или в воде"
        timeline.append(item)

    # Эпизоды стресса ≥ HIGH_STRESS подряд ≥ MIN_EPISODE_MIN (по сырым точкам,
    # интервал Garmin — 3 мин; короткие разрывы активностью не рвут эпизод).
    episodes = []
    start = last = None
    vals: list[int] = []
    for ts, val in stress_rows:
        if val >= HIGH_STRESS:
            if start is None:
                start, vals = ts, []
            last = ts
            vals.append(val)
        elif val >= 0 and start is not None:
            if (last - start) / 60000 >= MIN_EPISODE_MIN:
                episodes.append((start, last, vals))
            start = None
    if start is not None and (last - start) / 60000 >= MIN_EPISODE_MIN:
        episodes.append((start, last, vals))

    hr_resting = (hr_payload or {}).get("restingHeartRate")
    return {
        "window": (
            "календарный день 00:00–24:00 по часам устройства; точки до засыпания в начале "
            "суток — хвост ПРЕДЫДУЩЕГО вечера, а не ночь после событий этого дня"
        ),
        "device_utc_offset_hours": round(offset.total_seconds() / 3600, 2),
        "resting_hr": hr_resting,
        "avg_stress": stress_payload.get("avgStressLevel"),
        "max_stress": stress_payload.get("maxStressLevel"),
        "high_stress_episodes": [
            {
                "from": _local_hhmm(s, offset),
                "to": _local_hhmm(e, offset),
                "avg_stress": round(sum(v) / len(v)),
            }
            for s, e, v in episodes
        ],
        "timeline": timeline,
    }


def get_intraday(user_id: int, day: str, user_tz_offset: timedelta) -> dict:
    # Файлы синка в data/garmin/ — только владельца стенда (id из окружения).
    primary_id = int(os.getenv("BOTKIN_USER_ID") or os.getenv("HEALTHVAULT_USER_ID") or 0)
    stress, hr, source = _fetch(user_id, day, primary_id)
    if not stress:
        return {
            "date": day,
            "available": False,
            "reason": "Почасовых данных за этот день нет: Garmin не подключён или часы ещё не синхронизировались.",
        }
    result = build_timeline(stress, hr, user_tz_offset)
    result.update({"date": day, "available": True, "source": source, "has_heart_rate": bool(hr)})
    return result
