"""Поиск уже сохранённого документа, похожего на только что разобранный (#558)."""

from core.health.doc_duplicates import find_similar_document

CBC = {"Hb": 119, "WBC": 4.6, "RBC": 4.21, "PLT": 226, "ESR": 8}


def _doc(extracted, file="2026-09-24_aaaa1111.jpg", **extra):
    return {"file": file, "extracted": extracted, **extra}


def test_same_values_same_date_is_duplicate():
    saved = [_doc({"date": "2026-09-13", "values": dict(CBC)})]
    new = {"date": "2026-09-13", "values": dict(CBC)}
    assert find_similar_document(saved, new) is saved[0]


def test_reprint_with_same_values_but_missing_date_is_duplicate():
    saved = [_doc({"date": "2026-09-13", "values": dict(CBC)})]
    assert find_similar_document(saved, {"date": None, "values": dict(CBC)}) is saved[0]


def test_different_date_is_not_duplicate():
    saved = [_doc({"date": "2026-03-01", "values": dict(CBC)})]
    assert find_similar_document(saved, {"date": "2026-09-13", "values": dict(CBC)}) is None


def test_few_matching_values_is_not_duplicate():
    saved = [_doc({"date": "2026-09-13", "values": {"Hb": 119, "WBC": 4.6, "RBC": 4.0}})]
    new = {"date": "2026-09-13", "values": {"Hb": 119, "WBC": 5.9, "RBC": 4.5}}
    assert find_similar_document(saved, new) is None


def test_values_less_than_three_do_not_count():
    saved = [_doc({"date": "2026-09-13", "values": {"Hb": 119}})]
    assert find_similar_document(saved, {"date": "2026-09-13", "values": {"Hb": 119}}) is None


def test_no_values_same_date_kind_and_type_is_duplicate():
    ex = {"date": "2026-09-08", "doc_kind": "smear_pcr", "doc_type": "ПЦР на ВПЧ", "values": {}}
    saved = [_doc(dict(ex))]
    assert find_similar_document(saved, {**ex, "doc_type": " пцр на впч "}) is saved[0]


def test_no_values_different_type_is_not_duplicate():
    saved = [_doc({"date": "2026-09-08", "doc_kind": "imaging", "doc_type": "УЗИ почек", "values": {}})]
    new = {"date": "2026-09-08", "doc_kind": "imaging", "doc_type": "УЗИ матки", "values": {}}
    assert find_similar_document(saved, new) is None


def test_garbage_input_is_safe():
    assert find_similar_document([None, {"file": "x"}, _doc(None)], {"date": "2026-01-01", "values": dict(CBC)}) is None
    assert find_similar_document([], {}) is None


SMEAR_A = (
    "ДНК ВПЧ ВКР типов 31, 33, 35, 39, 45, 51 не обнаружены. Цитология: NILM, клетки зоны трансформации отсутствуют."
)
SMEAR_A2 = "ДНК ВПЧ ВКР 31, 33, 35, 39, 45, 51 — не обнаружены; цитограмма NILM, клеток зоны трансформации нет."
FLORA = "Ureaplasma urealyticum, Mycoplasma hominis, Candida albicans не обнаружены. Нарушений баланса микрофлоры не выявлено."


def test_same_page_photographed_twice_detected_by_summary():
    """#558: повторное фото мазка — названия сформулированы по-разному, резюме похожи."""
    saved = [
        _doc(
            {
                "date": "2026-09-08",
                "doc_kind": "smear_pcr",
                "doc_type": "ПЦР на ВПЧ ВКР",
                "summary": SMEAR_A,
                "values": {},
            }
        )
    ]
    new = {
        "date": "2026-09-08",
        "doc_kind": "smear_pcr",
        "doc_type": "ПЦР на ВПЧ высокого риска",
        "summary": SMEAR_A2,
        "values": {},
    }
    assert find_similar_document(saved, new) is saved[0]


def test_different_page_same_day_not_duplicate():
    saved = [
        _doc(
            {
                "date": "2026-09-08",
                "doc_kind": "smear_pcr",
                "doc_type": "ПЦР на ВПЧ ВКР",
                "summary": SMEAR_A,
                "values": {},
            }
        )
    ]
    new = {"date": "2026-09-08", "doc_kind": "smear_pcr", "doc_type": "Флороценоз", "summary": FLORA, "values": {}}
    assert find_similar_document(saved, new) is None


def test_imaging_with_differently_named_sizes_detected_by_summary():
    summary = "Левая почка 107×50 мм, правая 110×55 мм, ЧЛС не расширена. Заключение: диффузные изменения почек."
    saved = [
        _doc(
            {
                "date": "2026-09-13",
                "doc_kind": "imaging",
                "doc_type": "УЗИ почек",
                "summary": summary,
                "values": {"left_kidney_length": 107, "left_kidney_width": 50, "right_kidney_length": 110},
            }
        )
    ]
    new = {
        "date": "2026-09-13",
        "doc_kind": "imaging",
        "doc_type": "УЗИ почек",
        "summary": summary,
        "values": {"kidney_left_mm": 107, "kidney_left_w": 50, "kidney_right_mm": 110},
    }
    assert find_similar_document(saved, new) is saved[0]


def test_cancelled_archived_document_is_not_a_duplicate_target():
    ex = {"date": "2026-09-13", "values": dict(CBC)}
    cancelled = _doc(dict(ex), auto_archived=True, user_confirmed=False, reason="пользователь отменил разбор")
    restored = _doc(dict(ex), file="2026-09-24_bbbb2222.jpg", auto_archived=True, restored=True)
    assert find_similar_document([cancelled], dict(ex)) is None
    assert find_similar_document([restored], dict(ex)) is restored


def test_conflicting_numbers_block_text_match():
    summary = "Общий анализ крови: гемоглобин, лейкоциты, эритроциты, тромбоциты, СОЭ, лейкоцитарная формула."
    saved = [
        _doc(
            {
                "date": "2026-09-13",
                "doc_kind": "lab_panel",
                "doc_type": "Общий анализ крови",
                "summary": summary,
                "values": {"Hb": 119, "WBC": 4.6, "RBC": 4.21},
            }
        )
    ]
    new = {
        "date": "2026-09-13",
        "doc_kind": "lab_panel",
        "doc_type": "Общий анализ крови",
        "summary": summary,
        "values": {"Hb": 135, "WBC": 7.1, "RBC": 4.9},
    }
    assert find_similar_document(saved, new) is None


def test_second_page_of_same_lab_panel_is_not_duplicate():
    """Ревью #560: вторая страница той же биохимии — другие аналиты, общий текст."""
    summary = "Биохимический анализ крови, КДЛ: показатели обмена веществ, ферменты печени, электролиты."
    saved = [
        _doc(
            {
                "date": "2026-09-13",
                "doc_kind": "lab_panel",
                "doc_type": "Биохимия крови",
                "summary": summary,
                "values": {"ALT": 20, "AST": 22, "bilirubin_total": 12},
            }
        )
    ]
    new = {
        "date": "2026-09-13",
        "doc_kind": "lab_panel",
        "doc_type": "Биохимия крови",
        "summary": summary,
        "values": {"sodium": 140, "potassium": 4.3, "chloride": 101},
    }
    assert find_similar_document(saved, new) is None
