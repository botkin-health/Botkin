"""Паритет публичного base-URL для ссылок бота — config.settings.public_base_url (#205).

Единый источник для всех билдеров публичных ссылок (дашборд /mc/, отчёт /r/,
agent dashboard_url). До #205 домен хардкодился `https://botkin.health` в нескольких
местах → дев-стенд отдавал прод-ссылки. Теперь все билдеры зовут этот хелпер, и дев
может отдавать свой домен через env BOTKIN_PUBLIC_URL. Прод-поведение — дефолт botkin.health.
"""

from config.settings import public_base_url


def test_defaults_to_prod_domain_when_env_unset(monkeypatch):
    monkeypatch.delenv("BOTKIN_PUBLIC_URL", raising=False)
    assert public_base_url() == "https://botkin.health"


def test_uses_env_when_set(monkeypatch):
    monkeypatch.setenv("BOTKIN_PUBLIC_URL", "https://dev.botkin.health")
    assert public_base_url() == "https://dev.botkin.health"


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("BOTKIN_PUBLIC_URL", "https://dev.botkin.health/")
    assert public_base_url() == "https://dev.botkin.health"


def test_dashboard_link_builder_follows_env(monkeypatch):
    # Контракт билдеров /mc/ (/share, agent dashboard_url): f"{public_base_url()}/mc/{token}".
    monkeypatch.setenv("BOTKIN_PUBLIC_URL", "https://dev.botkin.health")
    assert f"{public_base_url()}/mc/abc123" == "https://dev.botkin.health/mc/abc123"


def test_report_link_builder_follows_env(monkeypatch):
    # Контракт билдера /r/ (/report): f"{public_base_url()}/r/{token}".
    monkeypatch.setenv("BOTKIN_PUBLIC_URL", "https://dev.botkin.health")
    assert f"{public_base_url()}/r/tok_xyz" == "https://dev.botkin.health/r/tok_xyz"


def test_builders_default_to_prod_when_env_unset(monkeypatch):
    monkeypatch.delenv("BOTKIN_PUBLIC_URL", raising=False)
    assert f"{public_base_url()}/mc/t" == "https://botkin.health/mc/t"
    assert f"{public_base_url()}/r/t" == "https://botkin.health/r/t"


def test_webapp_button_url_follows_env(monkeypatch):
    # Контракт menu-button «Дневник» (bot.py): f"{public_base_url()}/webapp/".
    # До консолидации кнопка читала отдельную PUBLIC_BASE_URL → дев-бот вёл мини-апп на прод
    # (дев-initData валидировался прод-токеном → 403 на вкладках). Теперь — тот же хелпер.
    monkeypatch.setenv("BOTKIN_PUBLIC_URL", "https://dev.botkin.health")
    assert f"{public_base_url()}/webapp/" == "https://dev.botkin.health/webapp/"


def test_webapp_button_url_defaults_to_prod_when_env_unset(monkeypatch):
    monkeypatch.delenv("BOTKIN_PUBLIC_URL", raising=False)
    assert f"{public_base_url()}/webapp/" == "https://botkin.health/webapp/"
