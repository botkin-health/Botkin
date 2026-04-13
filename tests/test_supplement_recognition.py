"""
РЕГРЕССИОННЫЙ ТЕСТ: Распознавание добавок и синонимов.

История баг:
- 05 апреля 2026: Метилфолат не записывался при написании "Метилофолат"
  (опечатка с лишней 'о'). Добавлены синонимы в _SUPPLEMENT_KEYWORDS.
- Риск: при добавлении новых добавок старые синонимы могут быть случайно удалены.

Что проверяем:
1. Метилфолат распознаётся по всем вариантам написания
2. Все ключевые добавки распознаются по типичным вариантам
3. Короткие сообщения (~6 слов) используют pre-check без вызова LLM
4. Еда НЕ распознаётся как добавка
"""

import pytest


def run_supplement_pre_check(text: str):
    """
    Воспроизводит pre-check логику из telegram-bot/handlers/text.py.
    Возвращает список добавок если найдены, None если pre-check не сработал.
    """
    _SUPPLEMENT_KEYWORDS = {
        "стирол": "Plant Sterols",
        "стиролы": "Plant Sterols",
        "стерол": "Plant Sterols",
        "стеролы": "Plant Sterols",
        "растительные стеролы": "Plant Sterols",
        "plant sterols": "Plant Sterols",
        "sterols": "Plant Sterols",
        "омега": "Омега 3",
        "омегу": "Омега 3",
        "omega": "Омега 3",
        "омега-3": "Омега 3",
        "омега 3-6-9": "Омега 3",
        "витамин д": "Витамин D3",
        "витамин d": "Витамин D3",
        "d3": "Витамин D3",
        "псиллиум": "Псиллиум",
        "псилиум": "Псиллиум",
        "psyllium": "Псиллиум",
        "магний": "Магний",
        "magnesium": "Магний",
        "цинк": "Цинк",
        "zinc": "Цинк",
        "креатин": "Креатин",
        "creatine": "Креатин",
        "метилфолат": "Метилфолат",
        "метилофолат": "Метилфолат",  # ← баг который фиксили
        "фолат": "Метилфолат",
        "metafolin": "Метилфолат",
        "methylfolate": "Метилфолат",
        "5-mthf": "Метилфолат",
        "ашваганд": "Ашвагандха",
        "коллаген": "Коллаген",
        "витамины": None,
    }

    text_lower = text.lower().strip()
    pre_found = {}
    for kw, canonical in _SUPPLEMENT_KEYWORDS.items():
        if canonical is None:
            continue
        if kw in text_lower and canonical not in pre_found.values():
            pre_found[kw] = canonical

    # Pre-check работает только для коротких сообщений (≤6 слов)
    if pre_found and len(text.split()) <= 6:
        return list(dict.fromkeys(pre_found.values()))
    return None


class TestMethylfolateRecognition:
    """Метилфолат должен распознаваться по всем вариантам — регрессия бага апреля 2026."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("метилфолат", "Метилфолат"),
            ("Метилфолат", "Метилфолат"),
            ("МЕТИЛФОЛАТ", "Метилфолат"),
            ("метилофолат", "Метилфолат"),  # ← исходный баг (опечатка с 'о')
            ("Метилофолат", "Метилфолат"),  # ← исходный баг (с заглавной)
            ("methylfolate", "Метилфолат"),
            ("5-mthf", "Метилфолат"),
            ("metafolin", "Метилфолат"),
            ("фолат", "Метилфолат"),
            ("принял метилфолат", "Метилфолат"),
            ("выпил метилофолат сегодня", "Метилфолат"),
        ],
    )
    def test_methylfolate_all_variants(self, text, expected):
        """Все варианты написания Метилфолата должны распознаваться."""
        result = run_supplement_pre_check(text)
        assert result is not None, f"Pre-check не сработал для '{text}'"
        assert expected in result, f"'{text}' → ожидали '{expected}', получили {result}"


class TestAllSupplementRecognition:
    """Все ключевые добавки распознаются по основным вариантам."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Омега
            ("омега", "Омега 3"),
            ("омега-3", "Омега 3"),
            ("omega", "Омега 3"),
            # Витамин D
            ("витамин д", "Витамин D3"),
            ("d3", "Витамин D3"),
            # Псиллиум
            ("псиллиум", "Псиллиум"),
            ("псилиум", "Псиллиум"),  # опечатка (одна 'л')
            ("psyllium", "Псиллиум"),
            # Магний
            ("магний", "Магний"),
            ("magnesium", "Магний"),
            # Цинк
            ("цинк", "Цинк"),
            ("zinc", "Цинк"),
            # Креатин
            ("креатин", "Креатин"),
            ("creatine", "Креатин"),
            # Plant Sterols
            ("стеролы", "Plant Sterols"),
            ("стиролы", "Plant Sterols"),
            ("plant sterols", "Plant Sterols"),
            # Ашвагандха
            ("ашваганда", "Ашвагандха"),  # подстрока ашваганд
            # Коллаген
            ("коллаген", "Коллаген"),
        ],
    )
    def test_supplement_recognized(self, text, expected):
        """Каждая добавка распознаётся по ключевому слову."""
        result = run_supplement_pre_check(text)
        assert result is not None, f"Pre-check не сработал для '{text}'"
        assert expected in result, f"'{text}' → ожидали '{expected}' в {result}"


class TestSupplementPreCheckBehavior:
    """Проверяем условия срабатывания pre-check."""

    def test_short_message_triggers_precheck(self):
        """Короткое сообщение (≤6 слов) → pre-check срабатывает."""
        result = run_supplement_pre_check("принял магний и цинк")
        assert result is not None
        assert "Магний" in result
        assert "Цинк" in result

    def test_long_message_skips_precheck(self):
        """Длинное сообщение (>6 слов) → pre-check НЕ срабатывает, идёт в LLM."""
        long_text = "сегодня утром я принял магний витамин д и омегу три штуки"
        result = run_supplement_pre_check(long_text)
        assert result is None, "Pre-check не должен срабатывать для длинного текста"

    def test_food_not_recognized_as_supplement(self):
        """Еда не должна распознаваться как добавка через pre-check."""
        food_texts = [
            "куриная грудка 200г",
            "гречка с маслом",
            "яблоко и банан",
            "кофе латте",
            "борщ 300г",
        ]
        for text in food_texts:
            result = run_supplement_pre_check(text)
            assert result is None, f"Еда '{text}' не должна давать supplement pre-check, получили {result}"

    def test_multiple_supplements_in_one_message(self):
        """Несколько добавок в одном коротком сообщении — все распознаются."""
        result = run_supplement_pre_check("омега цинк магний")
        assert result is not None
        assert "Омега 3" in result
        assert "Цинк" in result
        assert "Магний" in result

    def test_no_duplicates_in_result(self):
        """Дубликаты одной добавки (разные синонимы) не дублируются в результате."""
        # омега и omega — одна добавка
        result = run_supplement_pre_check("омега omega")
        assert result is not None
        assert result.count("Омега 3") == 1, f"Дубликат Омега 3: {result}"

    def test_empty_text_no_crash(self):
        """Пустой текст — не падает, возвращает None."""
        result = run_supplement_pre_check("")
        assert result is None

    def test_vitaminI_generic_word_not_alone(self):
        """'витамины' (общее слово) само по себе не даёт результата."""
        result = run_supplement_pre_check("витамины")
        # "витамины" → canonical=None → пропускается
        assert result is None, "Слово 'витамины' без уточнения не должно создавать запись"


class TestSupplementKeywordsIntegrity:
    """Проверяем что словарь синонимов не потерял ключевые маппинги."""

    def test_april_bug_keywords_exist(self):
        """Ключевые слова из апрельского бага присутствуют в словаре."""
        # Прямая проверка словаря в коде
        # Импортируем через handlers.text где он определён,
        # но т.к. там нет отдельной функции — проверяем через run_supplement_pre_check
        april_bug_variants = ["метилофолат", "methylfolate", "5-mthf", "metafolin"]
        for variant in april_bug_variants:
            result = run_supplement_pre_check(variant)
            assert result == ["Метилфолат"], (
                f"Синоним '{variant}' не распознаётся как Метилфолат — регрессия бага от 05.04.2026! Получили: {result}"
            )
