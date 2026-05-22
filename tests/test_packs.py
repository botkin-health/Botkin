"""Тесты для декларативного реестра packs."""

import pytest

from core.packs import PACKS, get_pack


def test_pack_is_frozen_dataclass():
    """Pack — immutable. Попытка изменить должна падать."""
    p = PACKS["generic"]
    with pytest.raises((AttributeError, TypeError)):
        p.name = "modified"


def test_all_packs_present():
    """Все известные packs зарегистрированы."""
    assert set(PACKS.keys()) == {
        "bariatric",
        "cardiac",
        "generic",
        "respiratory_allergic",
    }


def test_respiratory_allergic_pack_shape():
    """Новый pack для Игоря — корректная структура."""
    p = get_pack("respiratory_allergic")
    assert p.name == "respiratory_allergic"
    assert "asthma_allergy_panel" in p.focus_areas
    assert "vitamin_d" in p.focus_areas
    assert "tick_antibodies" in p.focus_areas
    assert "vitamin_d_trend" in p.dashboard_blocks
    assert "allergy_history" in p.dashboard_blocks


def test_get_pack_unknown_raises():
    """Неизвестный pack → ValueError с понятным сообщением."""
    with pytest.raises(ValueError) as exc_info:
        get_pack("does_not_exist")
    assert "does_not_exist" in str(exc_info.value)
    assert "respiratory_allergic" in str(exc_info.value)  # список available


def test_existing_packs_unchanged():
    """Регрессия: bariatric/cardiac/generic не сломались."""
    assert get_pack("bariatric").name == "bariatric"
    assert get_pack("cardiac").name == "cardiac"
    assert get_pack("generic").name == "generic"
