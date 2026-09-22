"""Тесты дедупликации по содержимому (issue #503 → #499)."""

import pytest

from handlers import doc_dedup


@pytest.fixture(autouse=True)
def _reset_dedup_cache():
    doc_dedup.reset()
    yield
    doc_dedup.reset()


def test_first_seen_is_not_duplicate():
    assert doc_dedup.is_duplicate(111, b"hello") is False


def test_same_content_second_time_is_duplicate():
    assert doc_dedup.is_duplicate(111, b"hello") is False
    assert doc_dedup.is_duplicate(111, b"hello") is True


def test_different_content_is_not_duplicate():
    assert doc_dedup.is_duplicate(111, b"hello") is False
    assert doc_dedup.is_duplicate(111, b"world") is False


def test_dedup_is_per_user():
    assert doc_dedup.is_duplicate(111, b"hello") is False
    assert doc_dedup.is_duplicate(222, b"hello") is False  # другой юзер — не повтор


def test_mark_false_checks_without_recording():
    assert doc_dedup.is_duplicate(111, b"hello", mark=False) is False
    # Не было помечено — второй вызов тоже не считает дублем.
    assert doc_dedup.is_duplicate(111, b"hello", mark=False) is False


def test_ttl_expiry_allows_resend_later(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(doc_dedup.time, "time", lambda: now[0])

    assert doc_dedup.is_duplicate(111, b"hello") is False
    assert doc_dedup.is_duplicate(111, b"hello") is True

    now[0] += doc_dedup.DEDUP_TTL_SECONDS + 1
    assert doc_dedup.is_duplicate(111, b"hello") is False


def test_reset_clears_single_user_only():
    doc_dedup.is_duplicate(111, b"a")
    doc_dedup.is_duplicate(222, b"b")

    doc_dedup.reset(111)

    assert doc_dedup.is_duplicate(111, b"a") is False  # забыт
    assert doc_dedup.is_duplicate(222, b"b") is True  # остался
