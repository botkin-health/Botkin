"""Тесты применения ДНК-теста во всей работе агента.

Путь сюда был через две неудачи: сначала данные лежали в KB и не читались
вовсе, потом читались только по правилу «вопрос про лекарство». Проверка
20.09.2026 показала, что на вопрос про билирубин агент про синдром Жильбера
не вспоминает. Перечислять темы бессмысленно — их столько же, сколько тем у
медицины, поэтому генетика приклеивается к промпту целиком.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core.health import genetics  # noqa: E402

PHARM = (
    "ФАРМАКОГЕНЕТИКА. КРАСНЫЕ: Клопидогрел — эффективность НИЗКАЯ, токсичность ВЫСОКАЯ. "
    "Симвастатин — токсичность ВЫСОКАЯ. Никотин — токсичность ВЫСОКАЯ. "
    "ЗЕЛЁНЫЕ: Розувастатин — статин ВЫБОРА. Тирзепатид — обычные."
)
FINDINGS = "НАХОДКИ. Синдром Жильбера — UGT1A1 rs887829 CT, носитель одной копии."
EXCLUDED = "ИСКЛЮЧЕНО. Наследственный гемохроматоз — не выявлен."


@pytest.fixture
def user(tmp_path, monkeypatch):
    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb_555.json").write_text(
        json.dumps(
            {
                "agent_corrections": {
                    "nutrition_targets_bju": {"value": "не генетика, не должно попасть"},
                    "genetics_pharmacogenetics": {"value": PHARM},
                    "genetics_findings": {"value": FINDINGS},
                    "genetics_excluded_diagnoses": {"value": EXCLUDED},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(genetics, "_PROJECT_ROOT", tmp_path)
    return SimpleNamespace(telegram_id=555, cohort="owner")


@pytest.fixture
def user_without_kb(tmp_path, monkeypatch):
    monkeypatch.setattr(genetics, "_PROJECT_ROOT", tmp_path)
    return SimpleNamespace(telegram_id=777, cohort="family")


# ── Загрузка ──────────────────────────────────────────────────────────────────


def test_loads_only_genetics_entries(user):
    data = genetics.load_genetics(user)
    assert set(data) == set(genetics.GENETICS_KEYS)
    assert "не генетика" not in json.dumps(data, ensure_ascii=False)


def test_no_kb_returns_empty(user_without_kb):
    assert genetics.load_genetics(user_without_kb) == {}
    assert genetics.genetics_prompt_block(user_without_kb) == ""


def test_broken_kb_does_not_raise(tmp_path, monkeypatch):
    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb_555.json").write_text("{битый json", encoding="utf-8")
    monkeypatch.setattr(genetics, "_PROJECT_ROOT", tmp_path)
    u = SimpleNamespace(telegram_id=555, cohort="owner")
    assert genetics.load_genetics(u) == {}


# ── Блок промпта ──────────────────────────────────────────────────────────────


def test_prompt_block_contains_all_three_entries(user):
    block = genetics.genetics_prompt_block(user)
    assert "Симвастатин" in block
    assert "Жильбера" in block
    assert "гемохроматоз" in block


def test_prompt_block_tells_agent_to_use_it_proactively(user):
    """Блок обязан требовать инициативы — иначе агент промолчит, как 20.09."""
    block = genetics.genetics_prompt_block(user)
    assert "ВО ВСЁМ" in block
    assert "САМ" in block


def test_prompt_block_capped(user, monkeypatch):
    monkeypatch.setattr(genetics, "MAX_BLOCK_CHARS", 200)
    block = genetics.genetics_prompt_block(user)
    assert len(block) <= 200 + 60
    assert "усечён" in block


# ── Проверка препарата ────────────────────────────────────────────────────────


def test_check_drug_exact(user):
    assert "токсичность ВЫСОКАЯ" in genetics.check_drug(user, "Симвастатин")


def test_check_drug_declension(user):
    """«симвастатина» в родительном падеже должно находить ту же запись."""
    assert genetics.check_drug(user, "симвастатина") is not None


def test_check_drug_case_and_yo(user):
    assert genetics.check_drug(user, "РОЗУВАСТАТИН") is not None


def test_check_drug_returns_only_its_segment(user):
    found = genetics.check_drug(user, "Клопидогрел")
    assert "Клопидогрел" in found
    assert "Розувастатин" not in found


def test_check_drug_unknown_returns_none(user):
    """Препарата нет в записи — молчим, а не сочиняем."""
    assert genetics.check_drug(user, "Парацетамол") is None


def test_check_drug_short_or_empty_name(user):
    assert genetics.check_drug(user, "") is None
    assert genetics.check_drug(user, "  ") is None


def test_check_drug_without_genetics(user_without_kb):
    assert genetics.check_drug(user_without_kb, "Симвастатин") is None
