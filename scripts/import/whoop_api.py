#!/usr/bin/env python3
"""Импорт данных WHOOP через официальный API v2 (OAuth 2.0, мультиюзер).

Запускается ВНУТРИ контейнера healthvault_bot (нужен доступ к БД + whoop_tokens.json):
    docker exec healthvault_bot python3 /app/scripts/import/whoop_api.py --uid REDACTED_ID
    docker exec healthvault_bot python3 /app/scripts/import/whoop_api.py --all --days 14

Токены подключённых юзеров — в data/cache/whoop_tokens.json (создаёт OAuth-callback,
см. webhook/whoop_oauth.py). Этот скрипт только ЧИТАЕТ токены и рефрешит при необходимости.

Маппинг WHOOP → БД:
  recovery (per cycle) → activity_log: heart_rate_avg=RHR, hrv=hrv_rmssd_milli,
                         raw_data={whoop_recovery_score, spo2, skin_temp_c, strain}
  sleep                → sleep_records (start/end, stages) + activity_log.sleep_hours
  body measurement     → weights (если Whoop отдаёт вес)

API: https://developer.whoop.com/api  (v2)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/telegram-bot")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("whoop")

API = "https://api.prod.whoop.com/developer/v2"


def _get(token: str, path: str, params: dict | None = None) -> dict:
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _paginate(token: str, path: str, start_iso: str, limit: int = 25) -> list[dict]:
    """Тянет коллекцию (cycle/sleep) с пагинацией по nextToken."""
    out: list[dict] = []
    next_token = None
    for _ in range(40):  # safety cap
        params = {"limit": limit, "start": start_iso}
        if next_token:
            params["nextToken"] = next_token
        data = _get(token, path, params)
        out.extend(data.get("records", []))
        next_token = data.get("next_token")
        if not next_token:
            break
    return out


def sync_user(uid: int, days: int = 14) -> dict:
    """Синхронизирует одного подключённого юзера. Возвращает сводку."""
    from webhook.whoop_oauth import get_valid_access_token
    from database import SessionLocal
    from sqlalchemy import text

    token = get_valid_access_token(str(uid))
    if not token:
        return {"uid": uid, "error": "not connected or token refresh failed"}

    start_iso = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = {"uid": uid, "recovery": 0, "sleep": 0}

    db = SessionLocal()
    try:
        # ── Recovery (через cycles) → activity_log ──────────────────────────
        cycles = _paginate(token, "/cycle", start_iso)
        for cyc in cycles:
            cid = cyc.get("id")
            cdate = (cyc.get("start") or "")[:10]
            if not cid or not cdate:
                continue
            strain = (cyc.get("score") or {}).get("strain")
            try:
                rec = _get(token, f"/cycle/{cid}/recovery")
            except requests.HTTPError:
                rec = {}
            score = rec.get("score") or {}
            if score.get("recovery_score") is None and strain is None:
                continue
            rhr = score.get("resting_heart_rate")
            hrv = score.get("hrv_rmssd_milli")
            raw = {
                k: v
                for k, v in {
                    "whoop_recovery_score": score.get("recovery_score"),
                    "spo2_percentage": score.get("spo2_percentage"),
                    "skin_temp_celsius": score.get("skin_temp_celsius"),
                    "whoop_strain": strain,
                }.items()
                if v is not None
            }
            db.execute(
                text(
                    """
                    INSERT INTO activity_log (user_id, date, heart_rate_avg, hrv, source, raw_data, synced_at)
                    VALUES (:uid, :d, :hr, :hrv, 'whoop', CAST(:raw AS jsonb), now())
                    ON CONFLICT (user_id, date) DO UPDATE SET
                      heart_rate_avg = COALESCE(EXCLUDED.heart_rate_avg, activity_log.heart_rate_avg),
                      hrv = COALESCE(EXCLUDED.hrv, activity_log.hrv),
                      raw_data = COALESCE(activity_log.raw_data, '{}'::jsonb) || EXCLUDED.raw_data,
                      source = CASE WHEN activity_log.source IS NULL OR activity_log.source='whoop'
                                    THEN 'whoop' ELSE activity_log.source END,
                      synced_at = now()
                    """
                ),
                {
                    "uid": uid,
                    "d": cdate,
                    "hr": int(rhr) if rhr is not None else None,
                    "hrv": int(round(hrv)) if hrv is not None else None,
                    "raw": __import__("json").dumps(raw),
                },
            )
            summary["recovery"] += 1

        # ── Sleep → sleep_records + activity_log.sleep_hours ────────────────
        sleeps = _paginate(token, "/activity/sleep", start_iso)
        for sl in sleeps:
            if sl.get("nap"):
                continue  # дневной сон не основной
            start = sl.get("start")
            end = sl.get("end")
            if not start or not end:
                continue
            sdate = end[:10]
            score = sl.get("score") or {}
            stage = score.get("stage_summary") or {}
            dur_ms = stage.get("total_in_bed_time_milli") or 0
            dur_h = round(dur_ms / 3_600_000, 2) if dur_ms else None
            deep = (stage.get("total_slow_wave_sleep_time_milli") or 0) // 60000
            rem = (stage.get("total_rem_sleep_time_milli") or 0) // 60000
            light = (stage.get("total_light_sleep_time_milli") or 0) // 60000
            awake = (stage.get("total_awake_time_milli") or 0) // 60000
            perf = score.get("sleep_performance_percentage")
            db.execute(
                text(
                    """
                    INSERT INTO sleep_records
                      (user_id, date, sleep_start, sleep_end, duration_hours, quality_score,
                       deep_sleep_minutes, rem_sleep_minutes, light_sleep_minutes, awake_minutes, source)
                    VALUES (:uid,:d,:st,:en,:dur,:q,:deep,:rem,:light,:awake,'whoop')
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "uid": uid,
                    "d": sdate,
                    "st": start,
                    "en": end,
                    "dur": dur_h,
                    "q": int(perf) if perf is not None else None,
                    "deep": int(deep),
                    "rem": int(rem),
                    "light": int(light),
                    "awake": int(awake),
                },
            )
            if dur_h:
                db.execute(
                    text(
                        """
                        INSERT INTO activity_log (user_id, date, sleep_hours, source, synced_at)
                        VALUES (:uid,:d,:dur,'whoop',now())
                        ON CONFLICT (user_id, date) DO UPDATE SET
                          sleep_hours = COALESCE(EXCLUDED.sleep_hours, activity_log.sleep_hours),
                          synced_at = now()
                        """
                    ),
                    {"uid": uid, "d": sdate, "dur": dur_h},
                )
            summary["sleep"] += 1

        db.commit()
    finally:
        db.close()
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", type=int, help="Telegram ID одного юзера")
    ap.add_argument("--all", action="store_true", help="Все подключённые юзеры из whoop_tokens.json")
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args(argv)

    from webhook.whoop_oauth import load_tokens

    if a.all:
        uids = [int(k.split(":")[1]) for k in load_tokens() if k.startswith("whoop:")]
    elif a.uid:
        uids = [a.uid]
    else:
        ap.error("укажи --uid <id> или --all")

    if not uids:
        log.info("Нет подключённых Whoop-юзеров.")
        return 0

    for uid in uids:
        s = sync_user(uid, a.days)
        if s.get("error"):
            log.info("⚠️  uid=%s: %s", uid, s["error"])
        else:
            log.info("✅ uid=%s: recovery=%s, sleep=%s записей", uid, s["recovery"], s["sleep"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
