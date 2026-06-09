"""Тесты фильтра артефактов пульса (Apple Watch off-wrist PPG → мусорный HR-min).

Контекст: HAE шлёт heart_rate_min сырым. Когда часы сняты/болтаются, PPG даёт
физиологически невозможные значения (7/9/13/21 bpm) — ложная брадикардия,
тревожит юзеров. Прецедент: у Андрея Походни 194 ложных «эпизода брадикардии <50»,
97 из них <30. Порог согласован с AndreyClaude 09.06.2026.

Правило (clinically-safe, НЕ режем реальную брадикардию кардиопациента):
  <30      → DROP (артефакт)
  [30,40)  → KEEP + флаг verify (могло быть реальной паузой)
  >=40     → KEEP (реальные паузы сна 40-49 — норма у кардиопациента)
"""

from core.health.hr_artifact import classify_hr_min


def test_impossible_low_values_dropped_as_artifact():
    # Реальные примеры off-wrist PPG у Андрея — физиологически невозможны
    for v in (7, 9, 13, 21, 29):
        assert classify_hr_min(v) == (None, False), f"{v} bpm должно дропаться как артефакт"


def test_borderline_30_to_40_kept_with_verify_flag():
    for v in (30, 35, 39):
        value, verify = classify_hr_min(v)
        assert value == v, f"{v} bpm нельзя дропать — может быть реальной паузой"
        assert verify is True, f"{v} bpm должно помечаться verify"


def test_real_sleep_bradycardia_kept_clean():
    # Реальный минимум сна Андрея 45-49; Reveal LINQ ловил настоящие паузы 40-46
    for v in (40, 46, 49):
        assert classify_hr_min(v) == (v, False), f"{v} bpm — реальная брадикардия, держим как есть"


def test_normal_hr_kept_clean():
    assert classify_hr_min(65) == (65, False)


def test_float_input_rounded():
    assert classify_hr_min(28.6) == (None, False)  # <30 → drop
    assert classify_hr_min(35.4) == (35, True)  # округление + verify
    assert classify_hr_min(46.5) == (46, False)  # banker's rounding (round(46.5)=46)


def test_none_input_is_safe():
    assert classify_hr_min(None) == (None, False)
