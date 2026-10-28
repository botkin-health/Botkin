import pytest

from core.health.onboarding_lists import (
    split_freetext,
    onboarding_list,
    is_known,
    merge_items,
    ALLERGY_KEYS,
    CONDITION_KEYS,
)


def test_split_freetext_keeps_icd_dot_and_comma():
    # Комма внутри пункта сохраняется, когда в строке есть сильный разделитель
    # (конец предложения) для другого пункта — иначе (см. ниже) она сама
    # становится границей (comma-fallback для списков без сильных разделителей).
    assert split_freetext("Астма (J45.0), лёгкая персистирующая. Ринит") == [
        "Астма (J45.0), лёгкая персистирующая",
        "Ринит",
    ]


def test_split_freetext_splits_on_sentence_and_semicolon():
    assert split_freetext("Гипертония; Диабет. Астма") == ["Гипертония", "Диабет", "Астма"]


def test_split_freetext_comma_fallback_for_plain_list():
    assert split_freetext("Гипертония, Диабет") == ["Гипертония", "Диабет"]


def test_onboarding_list_reads_first_nonempty_key():
    data = {"allergies": "", "food_allergies": "Пыльца берёзы"}
    assert onboarding_list(data, ALLERGY_KEYS) == ["Пыльца берёзы"]


def test_onboarding_list_accepts_list_value():
    data = {"chronic_conditions": ["Астма", "Гипертония"]}
    assert onboarding_list(data, CONDITION_KEYS) == ["Астма", "Гипертония"]


def test_onboarding_list_empty_when_missing():
    assert onboarding_list({}, ALLERGY_KEYS) == []
    assert onboarding_list(None, CONDITION_KEYS) == []


# --- merge_items / is_known (#645) -------------------------------------------


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        # регистр, ё, пробелы и пунктуация
        ("Артериальная гипертензия", "артериальная  гипертензия."),
        ("Стеатоз печени", "Стеатоз печёни"),
        # «ст.» / «степени» — одно и то же
        ("Гипертоническая болезнь II ст. (I10)", "Гипертоническая болезнь II степени (I10)"),
        # тот же текст без кода
        ("Артериальная гипертензия (I10)", "Артериальная гипертензия"),
        # код с другой детализацией (H52.2 ~ H52.20, I50 ~ I50.9)
        ("Астигматизм (H52.2)", "Астигматизм (H52.20)"),
        ("Сердечная недостаточность I (I50.9)", "Сердечная недостаточность I функционального класса (I50)"),
        # другая формулировка с тем же кодом
        ("Гипертоническая болезнь II ст. (I10)", "Артериальная гипертензия (I10)"),
        # противоречивый второй код при том же тексте в профиль не тащим
        ("Метаболический синдром (E88.9)", "Метаболический синдром (E88.81)"),
        # общее при наличии более подробного
        ("Остеохондроз пояснично-крестцового отдела позвоночника", "Остеохондроз позвоночника"),
        ("Протрузии дисков L1-L2, L3-L4, L4-L5", "Протрузия диска L3-L4"),
        # аллергены: склонения и синонимы
        ("кошка", "Кот"),
        ("клещи домашней пыли", "пылевой клещ"),
        ("Пыльца трав", "травы"),
    ],
)
def test_merge_items_skips_same_condition(existing, new):
    merged, added, refined = merge_items([existing], [new])
    assert (merged, added, refined) == ([existing], 0, 0)
    assert is_known(new, [existing])


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        # клинически значимые детали не теряем
        ("Протрузия диска L1-L2", "Протрузия диска L4-L5"),
        ("Митральная регургитация 1 степени", "Митральная регургитация 2 степени"),
        ("Ревматоидный артрит в анамнезе", "Ревматоидный артрит"),
        ("Рак молочной железы", "Подозрение на рак молочной железы"),
        # разные коды — разные состояния
        ("Сахарный диабет 2 типа (E11)", "Несахарный диабет (E23.2)"),
        # тот же код, но слишком разные формулировки — не склеиваем
        (
            "Двустворчатый аортальный клапан с кальцинозом (Q23.9)",
            "Комбинированный порок аортального клапана: стеноз и недостаточность (Q23.9)",
        ),
        # короткий пункт не растворяем в длинной сводке
        (
            "МР-признаки дегенеративно-дистрофических изменений шейного отдела позвоночника, нарушение статики",
            "Нарушение статики позвоночника",
        ),
        ("rCan f1 липокалин", "rCan f2"),
    ],
)
def test_merge_items_keeps_distinct(existing, new):
    merged, added, refined = merge_items([existing], [new])
    assert (merged, added, refined) == ([existing, new], 1, 0)
    assert not is_known(new, [existing])


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        ("Артериальная гипертензия", "Артериальная гипертензия (I10)"),
        ("Гипертоническая реакция", "Гипертоническая реакция на нагрузку"),
        ("Протрузия диска L1-L2", "Протрузии дисков L1-L2, L3-L4"),
    ],
)
def test_merge_items_refines_in_place(existing, new):
    merged, added, refined = merge_items(["Предиабет", existing, "Дислипидемия"], [new])
    assert (merged, added, refined) == (["Предиабет", new, "Дислипидемия"], 0, 1)


def test_merge_items_refined_item_absorbs_all_covered():
    existing = ["Протрузия диска L1-L2", "Предиабет", "Протрузия диска L4-L5"]
    merged, added, refined = merge_items(existing, ["Протрузии дисков L1-L2, L4-L5"])
    assert merged == ["Протрузии дисков L1-L2, L4-L5", "Предиабет"]
    assert (added, refined) == (0, 1)


def test_merge_items_does_not_replace_coded_item_with_uncoded():
    merged, _, refined = merge_items(
        ["Экзокринная недостаточность поджелудочной железы (K86.8)"],
        ["Экзокринная недостаточность функции поджелудочной железы"],
    )
    assert merged[0] == "Экзокринная недостаточность поджелудочной железы (K86.8)"
    assert refined == 0


def test_merge_items_dedups_within_batch_and_drops_blank():
    merged, added, _ = merge_items([], ["Гипертония", "  ", "гипертония", "Астма"])
    assert merged == ["Гипертония", "Астма"]
    assert added == 2
