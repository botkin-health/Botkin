"""Тесты дедупликации по содержимому (issue #503 → #499 → #516).

Issue #516: раньше был единственный флаг «видел / не видел», выставляемый при
приёме файла. Теперь — двухфазная отметка: `mark_in_progress` (при приёме),
`mark_saved` (при успешном сохранении), `clear` (при отмене/сбое) — чтобы
отменённый или сбойный документ не блокировал повторную отправку."""

import pytest

from handlers import doc_dedup


@pytest.fixture(autouse=True)
def _reset_dedup_cache():
    doc_dedup.reset()
    yield
    doc_dedup.reset()


def test_unseen_content_has_no_status():
    assert doc_dedup.status(111, b"hello") is None


def test_mark_in_progress_then_status_in_progress():
    doc_dedup.mark_in_progress(111, b"hello")
    assert doc_dedup.status(111, b"hello") == doc_dedup.STATUS_IN_PROGRESS


def test_mark_saved_then_status_saved():
    doc_dedup.mark_saved(111, b"hello")
    assert doc_dedup.status(111, b"hello") == doc_dedup.STATUS_SAVED


def test_mark_saved_overrides_in_progress():
    doc_dedup.mark_in_progress(111, b"hello")
    doc_dedup.mark_saved(111, b"hello")
    assert doc_dedup.status(111, b"hello") == doc_dedup.STATUS_SAVED


def test_clear_removes_mark_regardless_of_state():
    doc_dedup.mark_in_progress(111, b"hello")
    doc_dedup.clear(111, b"hello")
    assert doc_dedup.status(111, b"hello") is None

    doc_dedup.mark_saved(111, b"hello")
    doc_dedup.clear(111, b"hello")
    assert doc_dedup.status(111, b"hello") is None


def test_different_content_is_independent():
    doc_dedup.mark_saved(111, b"hello")
    assert doc_dedup.status(111, b"world") is None


def test_dedup_is_per_user():
    doc_dedup.mark_saved(111, b"hello")
    assert doc_dedup.status(222, b"hello") is None  # другой юзер — независим


def test_saved_ttl_expiry_allows_resend_later(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(doc_dedup.time, "time", lambda: now[0])

    doc_dedup.mark_saved(111, b"hello")
    assert doc_dedup.status(111, b"hello") == doc_dedup.STATUS_SAVED

    now[0] += doc_dedup.SAVED_TTL_SECONDS + 1
    assert doc_dedup.status(111, b"hello") is None


def test_in_progress_ttl_expiry_is_a_safety_net(monkeypatch):
    """clear() — основной способ снятия отметки; TTL — только страховка на
    случай если clear() почему-то не был вызван."""
    now = [1_000_000.0]
    monkeypatch.setattr(doc_dedup.time, "time", lambda: now[0])

    doc_dedup.mark_in_progress(111, b"hello")
    assert doc_dedup.status(111, b"hello") == doc_dedup.STATUS_IN_PROGRESS

    now[0] += doc_dedup.IN_PROGRESS_TTL_SECONDS + 1
    assert doc_dedup.status(111, b"hello") is None


def test_reset_clears_single_user_only():
    doc_dedup.mark_saved(111, b"a")
    doc_dedup.mark_saved(222, b"b")

    doc_dedup.reset(111)

    assert doc_dedup.status(111, b"a") is None  # забыт
    assert doc_dedup.status(222, b"b") == doc_dedup.STATUS_SAVED  # остался
