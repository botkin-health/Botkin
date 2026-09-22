# tests/test_doc_readability.py
"""Документный гейт (issue #509, переделано после ревью): не зависит от

реестра маркеров вообще — проверяет только, похож ли извлечённый текст
документа на нормальный текст (есть слова) или это точки/цифры от шрифта
без нужных глифов."""

from core.health.doc_readability import is_document_text_readable

# Реальный вывод PyMuPDF на PDF из репро #509 (кириллица шрифтом helv — глифов
# нет, рендерится точками; числа/даты/разделители остаются как есть).
BROKEN_TEXT = (
    "·········· ······· ·····\n"
    "····: 20.09.2026\n"
    "·······: 5.4 ·····/·\n"
    "·········: 88 ······/·\n"
    "····· ··········: 5.9 ·····/·\n"
    "····: 3.8 ·····/·\n"
    "···: 27 ··/·"
)


def test_broken_font_text_is_not_readable():
    assert is_document_text_readable(BROKEN_TEXT) is False


def test_empty_text_is_not_readable():
    assert is_document_text_readable("") is False
    assert is_document_text_readable(None) is False


def test_normal_russian_lab_report_is_readable():
    text = (
        "Результаты анализа крови от 20.09.2026\n"
        "Глюкоза: 5.4 ммоль/л\n"
        "Креатинин: 88 мкмоль/л\n"
        "Общий холестерин: 5.9 ммоль/л\n"
        "ЛПНП: 3.8 ммоль/л\n"
        "АЛТ: 27 Ед/л\n"
    )
    assert is_document_text_readable(text) is True


def test_short_gibberish_with_a_few_stray_letters_is_not_readable():
    """Пара случайных букв среди цифр (артефакт OCR) не должна засчитываться —

    нужно и достаточную долю букв, и достаточно отдельных «слов»."""
    text = "х: 1.2 у: 3 z: 88.0 к: 5"
    assert is_document_text_readable(text) is False
