# tests/test_doc_detect.py
"""Regex-эвристика core/health/doc_detect.looks_like_medical_document (issue #439)."""

from core.health.doc_detect import looks_like_medical_document


def test_lab_report_text_is_detected():
    text = """
    Общий анализ крови
    Гемоглобин: 148 г/л (норма 130-160)
    Лейкоциты: 6.2 10^9/л
    Глюкоза: 5.1 ммоль/л
    Референсные значения указаны рядом с результатом.
    Заключение: показатели в пределах нормы.
    """
    assert looks_like_medical_document(text) is True


def test_lab_name_and_units_are_detected():
    text = "KDL Лаборатория. Результат исследования. Ферритин 95 нг/мл. Витамин D 32 нг/мл."
    assert looks_like_medical_document(text) is True


def test_plain_article_is_not_detected():
    text = (
        "Сегодня на встрече обсуждали план работ на квартал, бюджет и найм. "
        "Договорились созвониться на следующей неделе и подготовить презентацию."
    )
    assert looks_like_medical_document(text) is False


def test_single_incidental_keyword_is_not_enough():
    """Один случайный медицинский термин в договоре/статье — не повод."""
    text = "В заключении договора стороны согласовали срок действия и порядок оплаты."
    assert looks_like_medical_document(text) is False


def test_empty_or_short_text_is_false():
    assert looks_like_medical_document("") is False
    assert looks_like_medical_document("коротко") is False


def test_invoice_text_is_not_detected():
    text = "Счёт на оплату №123. Итого к оплате: 4500 руб. Реквизиты банка указаны ниже. Спасибо за покупку!"
    assert looks_like_medical_document(text) is False


def test_repeated_single_keyword_is_not_enough():
    """Три повторения ОДНОГО И ТОГО ЖЕ слова — не три разных совпадения.

    Регресс-guard: старая реализация считала СУММАРНОЕ число совпадений
    (len(matches)), поэтому «заключение» x3 в одном документе набирало
    _MIN_MATCHES и ложно считалось анализом. Новая — считает РАЗЛИЧНЫЕ
    сработавшие паттерны, так что троекратное «заключение» — это всего
    один сработавший паттерн.
    """
    text = "Заключение по итогам проверки. В заключение добавим ещё одно заключение для верности."
    assert looks_like_medical_document(text) is False


def test_real_lab_snippet_is_detected():
    text = "Гемоглобин 145 г/л, референс 130–160; Глюкоза 5.1 ммоль/л."
    assert looks_like_medical_document(text) is True


def test_insurance_boilerplate_keywords_alone_is_not_enough():
    """Диагноз/МКБ/заключение по разу каждое — три РАЗНЫХ паттерна набираются,
    но это может быть строка из шаблона страхового полиса, а не бланк анализа.
    Без единицы измерения или референсного диапазона рядом — не считаем
    документом анализа."""
    text = (
        "В случае наступления страхового случая укажите диагноз (код МКБ) "
        "и приложите заключение врача к заявлению на выплату."
    )
    assert looks_like_medical_document(text) is False
