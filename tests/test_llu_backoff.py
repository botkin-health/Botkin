"""Юнит-тесты backoff-механизма LibreLinkUp (#141)."""

import time
import sys
import unittest.mock as mock
import pytest

# ---------------------------------------------------------------------------
# Загрузка модуля через тот же путь, что glucose_runtime.py, но под отдельным
# именем — чтобы не конфликтовать с prod-кэшем и иметь чистое состояние.
# ---------------------------------------------------------------------------


@pytest.fixture()
def llu(tmp_path):
    """Возвращает свежую копию librelinkup с изолированным backoff-состоянием."""
    import importlib.util
    from pathlib import Path

    modname = "_test_llu_backoff_isolated"
    # Убираем прошлый экземпляр если был (перезапуск тестов в том же процессе)
    sys.modules.pop(modname, None)

    path = Path(__file__).resolve().parents[1] / "scripts" / "import" / "librelinkup.py"
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod

    # Патчим тяжёлые зависимости до exec_module
    with mock.patch.dict(
        "sys.modules",
        {
            "pylibrelinkup": mock.MagicMock(),
            "requests": mock.MagicMock(),
            "psycopg2": mock.MagicMock(),
            "psycopg2.extras": mock.MagicMock(),
            "dotenv": mock.MagicMock(),
        },
    ):
        spec.loader.exec_module(mod)

    # Сбрасываем backoff-состояние в «чистый» старт
    mod._login_blocked_until = 0.0
    mod._login_fail_count = 0
    mod._cached_client = None

    # Направляем TOKEN_CACHE в tmp, чтобы тесты не читали/писали реальный кэш
    mod.TOKEN_CACHE = tmp_path / "token_cache.json"

    yield mod

    sys.modules.pop(modname, None)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_cooldown_blocks_login(llu):
    """Активный cooldown не допускает сетевой вызов get_client()."""
    llu._login_blocked_until = time.monotonic() + 999.0
    llu._login_fail_count = 1

    with mock.patch.object(llu, "_new_client") as mock_new:
        with pytest.raises(llu.LoginOnCooldownError) as exc_info:
            llu.get_cached_client()

    mock_new.assert_not_called()
    assert exc_info.value.retry_in > 0


def test_expired_cooldown_allows_login(llu):
    """После истечения cooldown ровно одна попытка логина."""
    llu._login_blocked_until = time.monotonic() - 1.0  # уже истёк
    llu._login_fail_count = 1

    fake_client = mock.MagicMock()
    fake_client.authenticate = mock.MagicMock()

    with mock.patch.object(llu, "_new_client", return_value=fake_client):
        with mock.patch.object(llu, "_save_token"):
            result = llu.get_cached_client()

    assert result is fake_client
    fake_client.authenticate.assert_called_once()
    assert llu._login_fail_count == 0
    assert llu._login_blocked_until == 0.0


def test_disk_token_bypasses_cooldown(llu, tmp_path):
    """Токен на диске позволяет создать клиент, даже если cooldown активен."""
    llu._login_blocked_until = time.monotonic() + 999.0
    llu._login_fail_count = 2

    fake_client = mock.MagicMock()
    with mock.patch.object(llu, "_client_from_saved_token", return_value=fake_client):
        result = llu.get_cached_client()

    assert result is fake_client
    # cooldown НЕ сбрасывается — логин не происходил
    assert llu._login_fail_count == 2


def test_failed_login_sets_backoff(llu):
    """Упавший authenticate() увеличивает счётчик и выставляет _login_blocked_until."""
    fake_client = mock.MagicMock()
    fake_client.authenticate.side_effect = RuntimeError("476 Cloudflare ban")

    with mock.patch.object(llu, "_new_client", return_value=fake_client):
        with pytest.raises(RuntimeError):
            llu.get_client()

    assert llu._login_fail_count == 1
    assert llu._login_blocked_until > time.monotonic()


def test_successful_login_resets_backoff(llu):
    """Успешный authenticate() обнуляет оба счётчика."""
    llu._login_fail_count = 3
    llu._login_blocked_until = time.monotonic() - 1.0  # истёк

    fake_client = mock.MagicMock()
    fake_client.authenticate = mock.MagicMock()

    with mock.patch.object(llu, "_new_client", return_value=fake_client):
        with mock.patch.object(llu, "_save_token"):
            llu.get_client()

    assert llu._login_fail_count == 0
    assert llu._login_blocked_until == 0.0
