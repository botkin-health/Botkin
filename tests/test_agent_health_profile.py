from types import SimpleNamespace
from core.agent_chat import _health_profile_block


def test_block_empty_when_no_profile():
    user = SimpleNamespace(onboarding_data={})
    assert _health_profile_block(user) == ""
    assert _health_profile_block(SimpleNamespace(onboarding_data=None)) == ""


def test_block_lists_allergies_only():
    user = SimpleNamespace(onboarding_data={"allergies": ["пыльца", "кошки"]})
    block = _health_profile_block(user)
    assert "Аллергии:" in block
    assert "пыльца" in block and "кошки" in block
    assert "Хронические диагнозы:" not in block


def test_block_lists_both():
    user = SimpleNamespace(
        onboarding_data={
            "allergies": ["пыльца"],
            "chronic_conditions": ["Бронхиальная астма (J45.0)"],
        }
    )
    block = _health_profile_block(user)
    assert "Аллергии: пыльца" in block
    assert "Бронхиальная астма (J45.0)" in block
    assert "Медпрофиль" in block
