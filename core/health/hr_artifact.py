"""Фильтр артефактов минимального пульса из Apple Watch (off-wrist PPG).

HAE шлёт heart_rate_min сырым, без маркировки «часы сняты». PPG вне запястья
выдаёт физиологически невозможные значения (7/9/13/21 bpm) → ложная брадикардия,
которая тревожит юзеров (прецедент: 194 ложных «эпизода <50» у Андрея Походни,
97 из них <30 bpm). Это systemic-проблема всех Apple Watch юзеров, не только его.

Порог согласован с AndreyClaude 09.06.2026. Сознательно НЕ режем по <40:
у кардиопациента реальный минимум сна 45-49, а Reveal LINQ ловил настоящие
паузы 40-46 — прятать реальную брадикардию нельзя.
"""

from typing import Optional, Tuple

# Ниже этого — заведомо артефакт PPG (off-wrist). Дропаем.
HR_MIN_ARTIFACT_FLOOR = 30
# [floor, verify_ceiling) — держим, но помечаем «проверить» (могло быть реальной паузой).
HR_MIN_VERIFY_CEILING = 40


def classify_hr_min(min_val: Optional[float]) -> Tuple[Optional[int], bool]:
    """Классифицировать минимальный пульс дня из HAE.

    Returns (value, needs_verify):
      • value=None        — артефакт, не сохранять heart_rate_min
      • (v, True)         — держим v, но флаг verify (пограничная зона 30-39)
      • (v, False)        — держим v как есть (реальная брадикардия / норма)
    """
    if min_val is None:
        return None, False
    if min_val < HR_MIN_ARTIFACT_FLOOR:
        return None, False
    value = int(round(float(min_val)))
    needs_verify = min_val < HR_MIN_VERIFY_CEILING
    return value, needs_verify
