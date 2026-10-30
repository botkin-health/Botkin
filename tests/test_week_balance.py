"""/week: блок баланса калорий говорит словами, выполнена ли цель дефицита (31.10.2026)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.commands import format_week_balance


def _text(consumed, tdee=2261, bmr=1907, active=354):
    return "\n".join(format_week_balance(consumed, tdee, bmr, active))


def test_deficit_below_target_is_not_marked_done():
    # Реальная неделя 24–30.10: 1998 из 2261 → 11.7%, цель 15% (1922)
    text = _text(1998)
    assert "2261 ккал (1907 в покое + 354 активность)" in text
    assert "Дефицит: 263 ккал (11.6% от расхода)" in text
    assert "есть до 1922 ккал" in text
    assert "меньше цели" in text and "~76 ккал" in text
    assert "✅" not in text


def test_target_reached():
    assert "✅ Цель выполнена." in _text(1850)


def test_too_deep_deficit():
    assert "слишком резко" in _text(1400)


def test_surplus():
    text = _text(2500)
    assert "Профицит: 239 ккал" in text and "Дефицита нет." in text


def test_unknown_expenditure():
    lines = format_week_balance(1998, 0, 0, 0)
    assert len(lines) == 1 and "неизвестен" in lines[0]
