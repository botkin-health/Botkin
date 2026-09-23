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


def test_short_readable_forms_are_not_rejected():
    """Короткий, но нормальный бланк — не мусор. Ложное отсечение здесь =
    тихая потеря настоящего анализа (ревью #509)."""
    for text in (
        "Глюкоза: 5.4 ммоль/л",
        "Гемоглобин 141 г/л\nСОЭ 8 мм/ч",
        "ПСА общий: 4.81 нг/мл",
        "HbA1c 5.9 %",
    ):
        assert is_document_text_readable(text), text


def test_control_char_garbage_from_broken_font_is_rejected():
    """Реальный класс мусора с прода: вместо букв — управляющие символы
    (доля букв 0.01–0.05), иногда с обрывками, похожими на «слова»."""
    garbage = "  \x04\x05\x06\x07\x05\x08\x05\t \x0b\x0c\x05 ab \x0e\x06 cd \x0f\x10\x11 12.5 \x12 7.8"
    assert not is_document_text_readable(garbage)
