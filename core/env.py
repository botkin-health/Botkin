"""Окружение, в котором запущен Botkin: prod / dev / local.

Задаётся переменной BOTKIN_ENV в compose-файле стенда (docker-compose.prod.yml,
docker-compose.dev.yml). Без переменной — 'local' (ноутбук разработчика, тесты).

Где используется:
- JWT агента: issuer/audience привязаны к окружению, поэтому токен, выпущенный
  продом, не проходит проверку на деве и наоборот, даже если per-user секреты
  когда-то совпали (ADR-0013).
- scripts/dev/seed_synthetic.py отказывается писать синтетику не в dev/local.
"""

import os

KNOWN_ENVS = ("prod", "dev", "local")
DEFAULT_ENV = "local"


def botkin_env() -> str:
    """Текущее окружение. Читается на каждый вызов (тесты меняют env через monkeypatch)."""
    value = (os.getenv("BOTKIN_ENV") or DEFAULT_ENV).strip().lower()
    if value not in KNOWN_ENVS:
        raise RuntimeError(f"BOTKIN_ENV={value!r} не из {KNOWN_ENVS}")
    return value


def jwt_issuer() -> str:
    """Claim `iss` агентских JWT: кто выпустил токен."""
    return f"botkin-{botkin_env()}"


def jwt_audience() -> str:
    """Claim `aud` агентских JWT: для какого API токен предназначен."""
    return f"botkin-agent-api-{botkin_env()}"


def agent_jwt_env_claims() -> dict:
    """iss/aud, которые кладут в payload оба места выпуска агентских JWT."""
    return {"iss": jwt_issuer(), "aud": jwt_audience()}
