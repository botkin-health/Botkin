#!/usr/bin/env python3
"""Импорт глюкозы CGM из LibreLinkUp → PostgreSQL (#96).

Архитектура (follower-паттерн):
  Один сервисный follower-аккаунт (dr@botkin.health) видит всех, кто его пригласил.
  `get_patients()` возвращает список Patient; маппинг patient_id → telegram_id
  берётся из таблицы cgm_connections (наполняется командой /connect_cgm).
  Точки пишутся в glucose_readings с upsert по (user_id, ts) — повторный прогон
  не плодит дубли.

Единицы: храним mmol/L. Конвертируем из value_in_mg_per_dl (явное поле API),
а не из value (оно зависит от локали аккаунта).

Креды: LLU_EMAIL / LLU_PASSWORD в .env. Регион — EU (аккаунт Netherlands).
API неофициальный (pylibrelinkup) — может меняться; см. docs/researches/2026-06-14-cgm-librelinkup-integration.md.

Использование:
    python scripts/import/librelinkup.py
    python scripts/import/librelinkup.py --dry-run
"""

import argparse
import os
import sys
import json
import logging
import threading
from pathlib import Path

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

# Коэффициент пересчёта mg/dL → mmol/L (молярная масса глюкозы 180.16).
MGDL_PER_MMOL = 18.0182


def mgdl_to_mmol(mgdl: float) -> float:
    """mg/dL → mmol/L, округление до 2 знаков (колонка Numeric(5,2))."""
    return round(mgdl / MGDL_PER_MMOL, 2)


def measurement_to_row(m) -> dict:
    """GlucoseMeasurement / GlucoseMeasurementWithTrend → строка glucose_readings.

    Чистая функция (без сети/БД) — отсюда вся проверяемая логика парсинга.
    trend есть только у latest() (GlucoseMeasurementWithTrend); у graph() — None.
    """
    trend = getattr(m, "trend", None)
    # ВАЖНО про время: LibreLinkUp отдаёт ДВА таймстампа —
    #   .timestamp        = локальное время устройства, НАИВНОЕ (без tz) → нельзя писать в timestamptz;
    #   .factory_timestamp = UTC (tz-aware) → канонический момент, его и храним в ts.
    # Если хранить .timestamp, Postgres примет наивное локальное за UTC → сдвиг на смещение TZ (#129).
    raw = {
        "timestamp_local": m.timestamp.isoformat() if m.timestamp else None,
        "factory_timestamp": m.factory_timestamp.isoformat() if m.factory_timestamp else None,
        "value_in_mg_per_dl": m.value_in_mg_per_dl,
        "type": getattr(m, "type", None),
        "measurement_color": getattr(m, "measurement_color", None),
        "glucose_units": getattr(m, "glucose_units", None),
        "is_high": getattr(m, "is_high", None),
        "is_low": getattr(m, "is_low", None),
    }
    return {
        "ts": m.factory_timestamp,  # UTC (tz-aware) — корректно ложится в timestamptz
        "value": mgdl_to_mmol(m.value_in_mg_per_dl),
        "trend": int(trend) if trend is not None else None,
        "raw": raw,
    }


def dedupe_by_ts(rows: list[dict]) -> list[dict]:
    """Схлопнуть точки с одинаковым ts (graph и latest пересекаются), сортировка по времени.

    Точки без ts (None — теоретически, если API не отдал factory_timestamp) отбрасываем,
    иначе sort упадёт на сравнении None с datetime.
    """
    by_ts = {r["ts"]: r for r in rows if r["ts"] is not None}
    return sorted(by_ts.values(), key=lambda r: r["ts"])


def collect_rows(client) -> dict[str, list[dict]]:
    """Для каждого пациента собрать точки: graph() (~12ч истории) + latest() (с трендом).

    Возвращает {patient_id(str): [row, ...]}. Сетевая часть, в тестах мокается.
    """
    result: dict[str, list[dict]] = {}
    for patient in client.get_patients():
        rows = [measurement_to_row(m) for m in client.graph(patient)]
        try:
            rows.append(measurement_to_row(client.latest(patient)))
        except Exception as e:  # latest опционален — не валим весь pull из-за одного пациента
            print(f"   ⚠️  latest() недоступен для {patient.patient_id}: {e}")
        result[str(patient.patient_id)] = dedupe_by_ts(rows)
    return result


# Персист JWT: LibreLinkUp login-эндпоинт временами отдаёт 476 на свежий authenticate(),
# но уже выданный токен качает данные. Поэтому храним токен на диске и переиспользуем —
# логин становится редким событием (только если токена нет/протух). Спасает и от рестарта
# контейнера, и от login-блока. См. #135.
TOKEN_CACHE = ROOT / "data" / "cache" / "llu_token.json"


def _new_client():
    """Сконструировать PyLibreLinkUp (регион EU) без авторизации. Креды из env."""
    email = os.getenv("LLU_EMAIL")
    password = os.getenv("LLU_PASSWORD")
    if not email or not password:
        raise RuntimeError("LLU_EMAIL / LLU_PASSWORD не заданы в .env")
    from pylibrelinkup import APIUrl, PyLibreLinkUp

    return PyLibreLinkUp(email=email, password=password, api_url=APIUrl.EU)


def _save_token(client) -> None:
    try:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps({"token": client.token, "account_id_hash": client.account_id_hash}))
    except Exception as e:
        logger.debug("не смог сохранить llu-токен: %s", e)


def get_client():
    """Авторизованный PyLibreLinkUp (регион EU): свежий логин + сохранение токена на диск."""
    client = _new_client()
    client.authenticate()
    _save_token(client)
    return client


def _client_from_saved_token():
    """Клиент с восстановленным с диска токеном (без логина). None — если токена нет/битый."""
    if not TOKEN_CACHE.exists():
        return None
    try:
        d = json.loads(TOKEN_CACHE.read_text())
        client = _new_client()
        client._set_token(d["token"])  # noqa: SLF001 — приватный API pylibrelinkup (версия пиннится)
        client._set_account_id_hash(d["account_id_hash"])  # noqa: SLF001
        return client
    except Exception as e:
        logger.debug("не смог восстановить llu-токен: %s", e)
        return None


# Кэш авторизованного клиента в памяти процесса. Под lock — on-demand refresh зовётся
# из asyncio.to_thread, возможны параллельные вызовы.
_cached_client = None
_cached_client_lock = threading.Lock()


def get_cached_client(reset: bool = False):
    """Переиспользуемый клиент: сперва токен с диска (без логина), иначе свежий логин.

    reset=True — выкинуть протухший токен (и in-memory, и файл) → форсировать новый логин.
    """
    global _cached_client
    with _cached_client_lock:
        if reset:
            _cached_client = None
            try:
                TOKEN_CACHE.unlink()
            except FileNotFoundError:
                pass
        if _cached_client is None:
            _cached_client = _client_from_saved_token() or get_client()
        return _cached_client


def fetch_patient_ids() -> list[str]:
    """ID всех пациентов, видимых follower-аккаунтом (через кэш-клиент, без лишнего логина)."""
    return [str(p.patient_id) for p in get_cached_client().get_patients()]


def refresh_glucose_for_telegram(telegram_id: int, db_url: str | None = None) -> int:
    """On-demand pull+upsert глюкозы для ОДНОГО пользователя. Возвращает число затронутых точек.

    No-op (0), если у юзера нет привязки в cgm_connections. Используется эндпоинтом
    recent_glucose для свежих данных «в момент вопроса». Сетевой/синхронный — звать в threadpool.
    """
    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url:
        return 0
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT patient_id FROM cgm_connections WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            if not row:
                return 0
            target_pid = str(row[0])

            try:
                client = get_cached_client()
                patient = next((p for p in client.get_patients() if str(p.patient_id) == target_pid), None)
                if patient is None:
                    return 0
                measurements = [measurement_to_row(m) for m in client.graph(patient)]
                try:
                    measurements.append(measurement_to_row(client.latest(patient)))
                except Exception as e:
                    logger.debug("latest() недоступен для %s: %s", target_pid, e)
            except Exception:
                # Протухший токен / сетевой сбой — сбросить кэш и повторить один раз.
                client = get_cached_client(reset=True)
                patient = next((p for p in client.get_patients() if str(p.patient_id) == target_pid), None)
                if patient is None:
                    return 0
                measurements = [measurement_to_row(m) for m in client.graph(patient)]
                try:
                    measurements.append(measurement_to_row(client.latest(patient)))
                except Exception as e:
                    logger.debug("latest() недоступен для %s: %s", target_pid, e)

            rows = dedupe_by_ts(measurements)
            ins, upd = upsert_rows(cur, telegram_id, rows)
        conn.commit()
        return ins + upd
    finally:
        conn.close()


def load_mapping(cur) -> dict[str, int]:
    """patient_id → telegram_id из cgm_connections."""
    cur.execute("SELECT patient_id, telegram_id FROM cgm_connections")
    return {str(pid): tid for pid, tid in cur.fetchall()}


def upsert_rows(cur, user_id: int, rows: list[dict]) -> tuple[int, int]:
    """Upsert точек в glucose_readings по (user_id, ts). Возвращает (inserted, updated)."""
    inserted = updated = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO glucose_readings (user_id, ts, value, trend, source, raw)
            VALUES (%s, %s, %s, %s, 'librelinkup', %s)
            ON CONFLICT (user_id, ts) DO UPDATE SET
                value = EXCLUDED.value,
                trend = EXCLUDED.trend,
                raw   = EXCLUDED.raw
            RETURNING (xmax = 0) AS was_inserted
            """,
            (user_id, r["ts"], r["value"], r["trend"], Json(r["raw"])),
        )
        if cur.fetchone()[0]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def main():
    parser = argparse.ArgumentParser(description="Импорт глюкозы LibreLinkUp → PostgreSQL")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL URL (или env DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, без записи в БД")
    args = parser.parse_args()

    print("🩸 LibreLinkUp — импорт глюкозы CGM...")
    client = get_cached_client()  # переиспользует токен с диска, без лишнего логина (#135)
    by_patient = collect_rows(client)
    total = sum(len(v) for v in by_patient.values())
    print(f"   Пациентов: {len(by_patient)}, точек собрано: {total}")

    if args.dry_run:
        for pid, rows in by_patient.items():
            last = rows[-1] if rows else None
            tail = f"последняя {last['ts']} = {last['value']} mmol/L" if last else "нет точек"
            print(f"   [DRY] {pid}: {len(rows)} точек, {tail}")
        return

    if not args.db_url:
        print("❌ DATABASE_URL не задан")
        sys.exit(1)

    conn = psycopg2.connect(args.db_url)
    try:
        with conn.cursor() as cur:
            mapping = load_mapping(cur)
            ins_total = upd_total = 0
            for pid, rows in by_patient.items():
                user_id = mapping.get(pid)
                if user_id is None:
                    print(f"   ⚠️  patient {pid} не привязан (нужен /connect_cgm) — пропуск {len(rows)} точек")
                    continue
                ins, upd = upsert_rows(cur, user_id, rows)
                ins_total += ins
                upd_total += upd
                print(f"   ✅ user {user_id}: +{ins} новых, {upd} обновлено")
        conn.commit()
    finally:
        conn.close()

    print(f"✅ Готово: {ins_total} вставлено, {upd_total} обновлено")


if __name__ == "__main__":
    main()
