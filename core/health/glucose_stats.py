"""Статистика глюкозы CGM: TIR, среднее, разброс (#96).

Чистые функции без зависимостей от БД/FastAPI — отсюда вся тестируемая арифметика.
Единицы — mmol/L. Целевой диапазон (Time-in-Range) — международный консенсус ADA/EASD:
3.9–10.0 mmol/L.
"""

from datetime import timezone

TIR_LOW = 3.9  # mmol/L — нижняя граница целевого диапазона
TIR_HIGH = 10.0  # mmol/L — верхняя граница целевого диапазона

# Порог устаревания CGM (#156). Libre 3 через LibreLinkUp подтягивает точку ~каждые
# 5 мин — разрыв >30 мин это уверенно реальный пробел (сенсор снят / синк лёг / бан
# LLU), а не джиттер. Влияет ТОЛЬКО на формулировки агента о свежести, не на данные.
GLUCOSE_STALE_THRESHOLD_MIN = 30


def glucose_staleness(last_ts, now, refresh_skipped: bool = False, threshold_min: int = GLUCOSE_STALE_THRESHOLD_MIN):
    """Признак устаревания свежей глюкозы (#156).

    `last_ts` — время последней точки в окне (tz-aware) или None если точек нет.
    Данные «устарели», если: точек нет; разрыв `now - last_ts` > порога; либо
    on-demand refresh был пропущен (cooldown/бан LLU) — тогда то, что в БД, заведомо
    не дотянуто до «сейчас». Возвращает `{is_stale, last_point_age_min}`.
    """
    if last_ts is None:
        return {"is_stale": True, "last_point_age_min": None}

    # SQLite (тесты) теряет tzinfo у DateTime(timezone=True); прод-Postgres отдаёт
    # aware. Нормализуем naive → UTC, чтобы вычитание не падало TypeError.
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)

    age_min = int((now - last_ts).total_seconds() // 60)
    is_stale = refresh_skipped or age_min > threshold_min
    return {"is_stale": is_stale, "last_point_age_min": age_min}


def compute_glucose_stats(values: list[float]) -> dict:
    """Сводка по списку значений глюкозы (mmol/L).

    Возвращает count и (если есть данные) avg/min/max/std и проценты времени
    ниже/в диапазоне/выше целевого (TIR). std — выборочное (делим на n-1, для %CV).
    """
    n = len(values)
    if n == 0:
        return {"count": 0}

    avg = sum(values) / n
    # Выборочная дисперсия (n-1): международный консенсус CGM (Danne 2017) считает
    # %CV = SD/mean по sample std. Для n=1 std не определена → 0.
    variance = sum((v - avg) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    std = variance**0.5

    below = sum(1 for v in values if v < TIR_LOW)
    above = sum(1 for v in values if v > TIR_HIGH)
    in_range = n - below - above

    return {
        "count": n,
        "avg": round(avg, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "std": round(std, 2),
        "tir_pct": round(100 * in_range / n, 1),
        "below_pct": round(100 * below / n, 1),
        "above_pct": round(100 * above / n, 1),
    }
