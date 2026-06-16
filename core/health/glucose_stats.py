"""Статистика глюкозы CGM: TIR, среднее, разброс (#96).

Чистые функции без зависимостей от БД/FastAPI — отсюда вся тестируемая арифметика.
Единицы — mmol/L. Целевой диапазон (Time-in-Range) — международный консенсус ADA/EASD:
3.9–10.0 mmol/L.
"""

TIR_LOW = 3.9  # mmol/L — нижняя граница целевого диапазона
TIR_HIGH = 10.0  # mmol/L — верхняя граница целевого диапазона


def compute_glucose_stats(values: list[float]) -> dict:
    """Сводка по списку значений глюкозы (mmol/L).

    Возвращает count и (если есть данные) avg/min/max/std и проценты времени
    ниже/в диапазоне/выше целевого (TIR). std — популяционное (делим на n).
    """
    n = len(values)
    if n == 0:
        return {"count": 0}

    avg = sum(values) / n
    variance = sum((v - avg) ** 2 for v in values) / n
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
