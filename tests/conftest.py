import os
import pytest
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

# Add root to path so database module can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Add telegram-bot to path so handlers can be imported in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

# Dummy-ключи ДО импорта модулей, требующих env — pytest можно запускать без
# ручных export'ов. setdefault не перетирает явно заданные значения.
_DUMMY_KEYS = {
    "TELEGRAM_BOT_TOKEN": "0000000000:CI_DUMMY_TOKEN_NOT_REAL",
    "BOT_TOKEN": "0000000000:CI_DUMMY_TOKEN_NOT_REAL",
    "ANTHROPIC_API_KEY": "sk-ant-ci-dummy-not-real",
    "OPENAI_API_KEY": "sk-ci-dummy-not-real",
    "GEMINI_API_KEY": "ci-dummy-not-real",
    "GOOGLE_API_KEY": "ci-dummy-not-real",
    # Прод-движок (database/__init__.py) требует DATABASE_URL и падает без неё.
    # Тесты используют отдельный in-memory SQLite и патчат SessionLocal, поэтому
    # сюда достаточно ленивого dummy-URL — реального коннекта по нему не будет.
    "DATABASE_URL": "postgresql://botkin_ci:botkin_ci@localhost:5432/botkin_ci",
    # Fernet-ключ для core/infra/secrets.py. Валидный по формату, но заведомо
    # тестовый: без него encrypt_secret осознанно падает, и тесты шифрования
    # пришлось бы обвешивать monkeypatch поштучно.
    "SECRETS_KEY": "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZXMta2V5LWFiY2Q=",
}
for _k, _v in _DUMMY_KEYS.items():
    os.environ.setdefault(_k, _v)

# Глобальный state_manager (services/state.py) в тестах — только в памяти:
# иначе хендлерные тесты писали бы JSON-состояния в data/state/ рабочей копии.
# Персистентность проверяет tests/test_state_persistence.py на tmp_path.
os.environ["BOT_STATE_DIR"] = ""

# .env под pytest НЕ читаем вовсе. config/settings.py и telegram-bot/bot.py делают
# load_dotenv(override=True): любой Settings(), созданный внутри теста, возвращал
# в os.environ настоящий TELEGRAM_BOT_TOKEN из .env поверх dummy. При прогоне из
# папки проекта на Google Drive (там лежит прод-.env) тест фидбека 19.10.2026
# отправил админу реальное сообщение через прод-бот. Тесты обязаны быть
# герметичными (в CI и в ~/botkin-* worktree .env и так нет), поэтому глушим
# load_dotenv ДО импорта любых модулей проекта — `from dotenv import load_dotenv`
# в них получит уже no-op.
import dotenv  # noqa: E402
import dotenv.main  # noqa: E402


def _no_dotenv(*_args, **_kwargs):
    return False


dotenv.load_dotenv = _no_dotenv
dotenv.main.load_dotenv = _no_dotenv

from database.models import Base  # noqa: E402

_TELEGRAM_HOST = "api.telegram.org"


class TelegramNetworkBlocked(RuntimeError):
    """Юнит-тест попытался сходить в реальный Telegram Bot API."""


class _TelegramGuard:
    def __init__(self):
        self.attempts: list[str] = []

    def block(self, what: str):
        self.attempts.append(what)
        raise TelegramNetworkBlocked(f"Юнит-тест пытался отправить запрос в Telegram: {what}. Замокай бота.")


@pytest.fixture(autouse=True)
def telegram_net_guard(monkeypatch):
    """Запрет реальных исходящих вызовов Telegram в юнит-тестах.

    Перехватываем на транспортном уровне все пути, которыми код ходит в Bot API:
    aiogram-сессию (feedback_api._make_bot, bot.py) и httpx/requests к
    api.telegram.org (agent_tools/feedback.py, owner_alerts, reports, …).
    Вызов падает исключением, но код фидбека/алертов best-effort и глотает
    исключения — поэтому попытка ещё и фиксируется, и тест валится на teardown.
    Тест, который проверяет сам гард, читает `telegram_net_guard.attempts`
    и очищает список.
    """
    guard = _TelegramGuard()

    from aiogram.client.session.aiohttp import AiohttpSession

    async def _aiogram_make_request(self, bot, method, timeout=None):
        guard.block(f"aiogram {type(method).__name__}")

    monkeypatch.setattr(AiohttpSession, "make_request", _aiogram_make_request)

    import httpx

    orig_async = httpx.AsyncHTTPTransport.handle_async_request
    orig_sync = httpx.HTTPTransport.handle_request

    async def _httpx_async(self, request):
        if request.url.host == _TELEGRAM_HOST:
            guard.block(f"httpx {request.method} {request.url.path.rsplit('/', 1)[-1]}")
        return await orig_async(self, request)

    def _httpx_sync(self, request):
        if request.url.host == _TELEGRAM_HOST:
            guard.block(f"httpx {request.method} {request.url.path.rsplit('/', 1)[-1]}")
        return orig_sync(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _httpx_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _httpx_sync)

    import requests.adapters
    from urllib.parse import urlsplit

    orig_send = requests.adapters.HTTPAdapter.send

    def _requests_send(self, request, *args, **kwargs):
        if urlsplit(request.url).hostname == _TELEGRAM_HOST:
            guard.block(f"requests {request.method} {request.url.rsplit('/', 1)[-1]}")
        return orig_send(self, request, *args, **kwargs)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _requests_send)

    yield guard

    if guard.attempts:
        pytest.fail(f"Тест пытался отправить запрос в реальный Telegram: {guard.attempts}", pytrace=False)


@pytest.fixture(autouse=True)
def _no_real_llm_keys(monkeypatch):
    """Юнит-тесты не должны ходить в реальные LLM API за деньги.

    config/settings.py делает load_dotenv(override=True) — при локальном прогоне
    реальные ключи из .env попадают в окружение и в кэшированный Settings.
    Принудительно подменяем на dummy в каждом тесте: забытый мок упадёт
    с invalid api key вместо тихого платного запроса.
    """
    for k, v in _DUMMY_KEYS.items():
        monkeypatch.setenv(k, v)
    try:
        from config.settings import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "telegram_bot_token", _DUMMY_KEYS["TELEGRAM_BOT_TOKEN"], raising=False)
        monkeypatch.setattr(s, "anthropic_api_key", _DUMMY_KEYS["ANTHROPIC_API_KEY"], raising=False)
        monkeypatch.setattr(s, "openai_api_key", _DUMMY_KEYS["OPENAI_API_KEY"], raising=False)
        monkeypatch.setattr(s, "gemini_api_key", _DUMMY_KEYS["GEMINI_API_KEY"], raising=False)
        monkeypatch.setattr(s, "google_api_key", _DUMMY_KEYS["GOOGLE_API_KEY"], raising=False)
    except Exception:
        pass


# Setup in-memory SQLite database
# Use check_same_thread=False for SQLite with threaded tests if needed
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_session_local(test_db):
    """Patches SessionLocal in all modules that use it in tests"""
    patches = [
        patch("core.health.supplements.SessionLocal", return_value=test_db),
        patch("services.nutrition_service.SessionLocal", return_value=test_db),
        patch("core.health.weekly_nutrition.SessionLocal", return_value=test_db),
        patch("core.health.garmin_data.SessionLocal", return_value=test_db),
    ]

    for p in patches:
        p.start()

    yield test_db

    for p in patches:
        p.stop()
