"""Характеризующие + security тесты подписи WHOOP OAuth state.

Легитимное поведение (round-trip, отклонение подделки) должно сохраниться
после фикса. Security-инварианты (нет публичного fallback-секрета, полная
длина подписи) сейчас КРАСНЫЕ, зеленеют после фикса.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))


@pytest.fixture
def whoop(monkeypatch):
    monkeypatch.setenv("WHOOP_STATE_SECRET", "test-secret-not-public-xyz")
    from webhook import whoop_oauth

    return whoop_oauth


# ── Характеризующие: легитимный путь не меняется ─────────────────────────────
def test_state_roundtrip(whoop):
    """_parse_state(_make_state(uid)) == uid — валидный state распознаётся."""
    for uid in ("895655", "1", "999999999"):
        assert whoop._parse_state(whoop._make_state(uid)) == uid


def test_forged_signature_rejected(whoop):
    """Подделанная подпись отвергается (нельзя привязать чужой uid)."""
    assert whoop._parse_state("895655.deadbeefdeadbeef") is None
    assert whoop._parse_state("895655.") is None
    assert whoop._parse_state("no-dot-here") is None


def test_state_depends_on_secret(whoop, monkeypatch):
    """Подпись, сделанная другим секретом, не проходит проверку."""
    state = whoop._make_state("895655")
    monkeypatch.setenv("WHOOP_STATE_SECRET", "a-completely-different-secret")
    assert whoop._parse_state(state) is None


# ── Security-инварианты (RED сейчас → GREEN после фикса) ──────────────────────
def test_no_public_fallback_secret(monkeypatch):
    """Без WHOOP_STATE_SECRET и APPLE_HEALTH_TOKEN секрет НЕ должен молча
    становиться публичным литералом 'botkin-whoop' (он в open-source репо)."""
    monkeypatch.delenv("WHOOP_STATE_SECRET", raising=False)
    monkeypatch.delenv("APPLE_HEALTH_TOKEN", raising=False)
    from webhook import whoop_oauth

    with pytest.raises((RuntimeError, ValueError)):
        whoop_oauth._state_secret()


def test_signature_full_length(whoop):
    """Подпись state — полный SHA-256 hexdigest (64 симв.), не усечённый до 64
    бит (16 симв.), чтобы исключить brute-force при известном uid."""
    sig = whoop._sign("895655")
    assert len(sig) == 64, f"подпись усечена до {len(sig)} симв. — слабая стойкость"
