"""Тесты i18n для doctor-report (#300): резолвинг языка, полнота словаря, LLM-перевод."""

from services.report_i18n import CHROME, SUPPORTED_LANGS, resolve_report_language


def test_explicit_wins_over_language_code():
    assert resolve_report_language("en", "ru") == "en"
    assert resolve_report_language("ru", "en-US") == "ru"


def test_language_code_en_prefix():
    assert resolve_report_language(None, "en") == "en"
    assert resolve_report_language(None, "en-US") == "en"


def test_fallback_ru():
    assert resolve_report_language(None, None) == "ru"
    assert resolve_report_language(None, "de") == "ru"
    assert resolve_report_language("fr", None) == "ru"  # невалидный explicit + нет кода → ru


def test_invalid_explicit_falls_through_to_language_code():
    # Невалидный explicit игнорируется и решает language_code (документированная семантика).
    assert resolve_report_language("fr", "en") == "en"
    assert resolve_report_language("fr", "ru") == "ru"


def test_catalog_has_both_languages():
    assert set(CHROME) == set(SUPPORTED_LANGS) == {"ru", "en"}
    assert set(CHROME["ru"]) == set(CHROME["en"])
    assert set(CHROME["ru"]["sections"]) == set(CHROME["en"]["sections"])
