"""Импорт исторической глюкозы из CSV-экспорта LibreView (libreview.com).

Зачем: follower-канал LibreLinkUp (`librelinkup.py`) отдаёт только ~12ч истории
(`client.graph`). Чтобы залить ВСЮ историю с момента установки сенсора, владелец
сенсора выгружает CSV из своего аккаунта LibreView и присылает боту — этот модуль
парсит файл и upsert'ит точки в `glucose_readings` (source='libreview_csv').

Парсер — чистая функция (`parse_libreview_csv`), без сети/БД, отсюда вся
проверяемая логика. Загрузка в БД (`import_libreview_csv`) — отдельно, psycopg2
импортируется лениво.

Формат CSV LibreView (пример, EU/mmol/L):
    Имя пациента,...                          ← строка-метадата (пропускаем)
    Device,Serial Number,Device Timestamp,Record Type,Historic Glucose mmol/L,Scan Glucose mmol/L,...
    FreeStyle Libre 3,xxx,15-06-2026 08:32,0,5.4,,...   ← Record Type 0 = авто (каждые 15 мин)
    FreeStyle Libre 3,xxx,15-06-2026 08:33,1,,5.6,...    ← Record Type 1 = ручной скан

Тонкости (см. #163 follow-up):
- Единицы: в заголовке либо mmol/L, либо mg/dL → mg/dL делим на 18.0182.
- Device Timestamp — НАИВНОЕ локальное время устройства. Конвертируем в UTC по TZ юзера
  (как в #129 — в `glucose_readings.ts` строго UTC).
- Порядок день/месяц (DD-MM vs MM-DD) зависит от локали аккаунта. Определяем по данным:
  если в каком-то ряду первое число >12 → день-первым; если второе >12 → месяц-первым.
- Только Record Type 0/1 несут глюкозу; 4/5/6 (инсулин/углеводы/заметки) — пропускаем.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MGDL_TO_MMOL = 18.0182  # делитель mg/dL → mmol/L

# Record Type в экспорте LibreView
_RT_HISTORIC = "0"  # авто-замер сенсора (каждые ~15 мин)
_RT_SCAN = "1"  # ручной скан

# Суффиксы времени, которые встречаются в Device Timestamp.
_TIME_SUFFIXES = ("%H:%M", "%H:%M:%S", "%I:%M %p")


class LibreViewParseError(ValueError):
    """CSV не похож на экспорт глюкозы LibreView (нет нужных колонок)."""


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# Заголовки LibreView ЛОКАЛИЗОВАНЫ по языку аккаунта. Матчим языконезависимо
# по подстрокам (EN + RU; RU — стандартные термины Abbott). Если перевод чуть иной —
# парсер упадёт с понятной ошибкой, а не молча испортит данные.
def _is_timestamp_col(c: str) -> bool:
    return "device timestamp" in c or "метка времени" in c


def _is_record_type_col(c: str) -> bool:
    return "record type" in c or "тип записи" in c


def _is_historic_glucose_col(c: str) -> bool:
    return "historic glucose" in c or ("глюкоз" in c and "прошл" in c)


def _is_scan_glucose_col(c: str) -> bool:
    return "scan glucose" in c or ("глюкоз" in c and "скан" in c)


def _is_mgdl(c: str) -> bool:
    return "mg/dl" in c or "мг/дл" in c


def _find_glucose_columns(header: list[str]) -> tuple[int | None, int | None, str]:
    """Вернуть (idx_historic, idx_scan, unit). unit ∈ {'mmol','mgdl'}."""
    idx_hist = idx_scan = None
    unit = "mmol"
    for i, col in enumerate(header):
        c = _norm(col)
        if _is_historic_glucose_col(c):
            idx_hist = i
            unit = "mgdl" if _is_mgdl(c) else "mmol"
        elif _is_scan_glucose_col(c):
            idx_scan = i
            if _is_mgdl(c):
                unit = "mgdl"
    return idx_hist, idx_scan, unit


def _detect_day_first(raw_timestamps: list[str]) -> bool:
    """Определить порядок: True = день-первым (DD-MM), False = месяц-первым (MM-DD).

    Эвристика по данным: берём первые два числа таймстампа. Если где-то первое >12 —
    это день (день-первым). Если где-то второе >12 — месяц-первым. По умолчанию (всё ≤12,
    различить нельзя) — день-первым (EU/RU локаль, наш основной кейс).
    """
    for ts in raw_timestamps:
        nums = re.findall(r"\d+", ts)
        if len(nums) >= 2:
            a, b = int(nums[0]), int(nums[1])
            if a > 12:
                return True
            if b > 12:
                return False
    return True


def _parse_timestamp(raw: str, day_first: bool) -> datetime | None:
    """Распарсить наивный таймстамп LibreView. Возвращает naive datetime или None."""
    raw = raw.strip()
    order = "%d-%m-%Y" if day_first else "%m-%d-%Y"
    # LibreView чаще через '-', но встречается '/'. Нормализуем '/' → '-'.
    candidate = raw.replace("/", "-")
    for suffix in _TIME_SUFFIXES:
        try:
            return datetime.strptime(candidate, f"{order} {suffix}")
        except ValueError:
            continue
    return None


def parse_libreview_csv(content: str, tz: ZoneInfo) -> tuple[list[dict], dict]:
    """Распарсить CSV-экспорт LibreView → (rows, meta).

    rows: [{"ts": aware UTC datetime, "value": mmol/L float, "trend": None, "raw": {...}}]
    meta: сводка для пользователя/логов (unit, day_first, counts, диапазон дат, skipped).

    Бросает LibreViewParseError, если это не похоже на экспорт глюкозы.
    """
    # Разделитель: LibreView обычно ',', но локали бывают ';' (и десятичная запятая внутри).
    # Сниффер на таких смешанных данных промахивается → выбираем по строке-заголовку:
    # тот разделитель, что даёт больше всего полей в строке с маркером таймстампа (EN/RU).
    header_line = next(
        (ln for ln in content.splitlines() if _is_timestamp_col(ln.lower())),
        "",
    )
    delimiter = max(",;\t", key=lambda d: header_line.count(d)) if header_line else ","

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    all_rows = [r for r in reader if r and any(cell.strip() for cell in r)]

    # Найти строку-заголовок (маркеры таймстампа + типа записи; язык аккаунта любой).
    header_idx = None
    for i, row in enumerate(all_rows[:10]):
        joined = _norm(delimiter.join(row))
        if _is_timestamp_col(joined) and _is_record_type_col(joined):
            header_idx = i
            break
    if header_idx is None:
        raise LibreViewParseError(
            "Не найдена строка-заголовок LibreView (нет колонок таймстампа устройства / типа записи)"
        )

    header = all_rows[header_idx]
    norm_header = [_norm(c) for c in header]
    idx_ts = next((i for i, c in enumerate(norm_header) if _is_timestamp_col(c)), None)
    idx_rt = next((i for i, c in enumerate(norm_header) if _is_record_type_col(c)), None)
    if idx_ts is None or idx_rt is None:
        raise LibreViewParseError("Нет обязательной колонки (таймстамп устройства / тип записи)")

    idx_hist, idx_scan, unit = _find_glucose_columns(header)
    if idx_hist is None and idx_scan is None:
        raise LibreViewParseError("Нет колонок 'Historic Glucose' / 'Scan Glucose'")

    data_rows = all_rows[header_idx + 1 :]

    # Сначала определить порядок день/месяц по всем таймстампам.
    raw_ts = [r[idx_ts] for r in data_rows if len(r) > idx_ts and r[idx_ts].strip()]
    day_first = _detect_day_first(raw_ts)

    rows: list[dict] = []
    skipped_non_glucose = 0
    skipped_bad = 0
    for r in data_rows:
        if len(r) <= max(idx_ts, idx_rt):
            skipped_bad += 1
            continue
        rt = r[idx_rt].strip()
        if rt == _RT_HISTORIC and idx_hist is not None:
            val_cell = r[idx_hist] if len(r) > idx_hist else ""
        elif rt == _RT_SCAN and idx_scan is not None:
            val_cell = r[idx_scan] if len(r) > idx_scan else ""
        else:
            skipped_non_glucose += 1
            continue

        val_cell = (val_cell or "").strip().replace(",", ".")
        if not val_cell:
            skipped_bad += 1
            continue
        try:
            value = float(val_cell)
        except ValueError:
            skipped_bad += 1
            continue
        if unit == "mgdl":
            value = round(value / MGDL_TO_MMOL, 2)

        naive = _parse_timestamp(r[idx_ts], day_first)
        if naive is None:
            skipped_bad += 1
            continue
        ts_utc = naive.replace(tzinfo=tz).astimezone(timezone.utc)

        rows.append(
            {
                "ts": ts_utc,
                "value": value,
                "trend": None,
                "raw": {"record_type": rt, "source_unit": unit, "device_ts": r[idx_ts].strip()},
            }
        )

    # Дедуп по ts (последняя запись на момент побеждает — scan важнее historic при совпадении).
    by_ts: dict[datetime, dict] = {}
    for row in rows:
        by_ts[row["ts"]] = row
    deduped = sorted(by_ts.values(), key=lambda x: x["ts"])

    meta = {
        "unit": unit,
        "day_first": day_first,
        "glucose_points": len(deduped),
        "skipped_non_glucose": skipped_non_glucose,
        "skipped_bad": skipped_bad,
        "first_ts": deduped[0]["ts"].isoformat() if deduped else None,
        "last_ts": deduped[-1]["ts"].isoformat() if deduped else None,
    }
    return deduped, meta


def import_libreview_csv(content: str, user_id: int, tz: ZoneInfo, db_url: str) -> dict:
    """Распарсить CSV и upsert'нуть в glucose_readings. Возвращает сводку.

    psycopg2 импортируется лениво — парсер тестируется без БД.
    """
    import psycopg2
    from psycopg2.extras import Json, execute_values

    rows, meta = parse_libreview_csv(content, tz)
    if not rows:
        return {"status": "empty", "inserted": 0, "updated": 0, **meta}

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # Сколько уже есть в окне импорта — для расчёта inserted vs updated.
            cur.execute(
                "SELECT count(*) FROM glucose_readings WHERE user_id=%s AND ts BETWEEN %s AND %s",
                (user_id, rows[0]["ts"], rows[-1]["ts"]),
            )
            existing = cur.fetchone()[0]
            execute_values(
                cur,
                """
                INSERT INTO glucose_readings (user_id, ts, value, trend, source, raw)
                VALUES %s
                ON CONFLICT (user_id, ts) DO UPDATE SET
                    value = EXCLUDED.value,
                    raw   = EXCLUDED.raw,
                    source = EXCLUDED.source
                """,
                [(user_id, r["ts"], r["value"], r["trend"], "libreview_csv", Json(r["raw"])) for r in rows],
                template="(%s, %s, %s, %s, %s, %s)",
            )
            cur.execute(
                "SELECT count(*) FROM glucose_readings WHERE user_id=%s AND ts BETWEEN %s AND %s",
                (user_id, rows[0]["ts"], rows[-1]["ts"]),
            )
            after = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    inserted = max(0, after - existing)
    return {
        "status": "ok",
        "inserted": inserted,
        "updated": len(rows) - inserted,
        "total_in_file": len(rows),
        **meta,
    }
