"""Тесты extract_date_from_text — относительная/явная дата в тексте еды.

Прецедент 30.05.2026: «Обед вчера: …» не распознавал дату → запись на сегодня.
"""

import importlib.util
import os
from datetime import datetime, timedelta, timezone


MSK = timezone(timedelta(hours=3))

_path = os.path.join(os.path.dirname(__file__), "..", "telegram-bot", "handlers", "text.py")
_spec = importlib.util.spec_from_file_location("tg_text_for_test", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_date_from_text = _mod.extract_date_from_text


def _ago(days: int) -> str:
    return (datetime.now(MSK) - timedelta(days=days)).strftime("%Y-%m-%d")


def test_vchera_midstring_keeps_prefix():
    """«Обед вчера: рыбные шарики» → вчера, без слова 'вчера', еда сохранена."""
    date_str, clean = extract_date_from_text("Обед вчера: рыбные шарики")
    assert date_str == _ago(1)
    assert "вчера" not in clean.lower()
    assert "рыбные шарики" in clean.lower()
    assert "обед" in clean.lower()  # префикс не потерян


def test_vchera_at_start():
    date_str, clean = extract_date_from_text("вчера ужин: омлет")
    assert date_str == _ago(1)
    assert "вчера" not in clean.lower()
    assert "омлет" in clean.lower()


def test_pozavchera():
    date_str, clean = extract_date_from_text("позавчера обед")
    assert date_str == _ago(2)
    assert "позавчера" not in clean.lower()


def test_month_name_still_works():
    """Регрессия: «29 мая ужин» уже работал — не сломать."""
    date_str, clean = extract_date_from_text("ужин 29 мая: салат")
    assert date_str is not None
    assert date_str.endswith("-05-29")
    assert "салат" in clean.lower()


def test_dd_mm_still_works():
    """Регрессия: DD.MM."""
    date_str, clean = extract_date_from_text("15.03 завтрак")
    assert date_str is not None
    assert date_str.endswith("-03-15")
    assert "завтрак" in clean.lower()


def test_no_date_returns_none():
    date_str, clean = extract_date_from_text("омлет 300 ккал")
    assert date_str is None
    assert clean == "омлет 300 ккал"
