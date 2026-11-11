"""Граница данных прод ↔ дев (ADR-0013): JWT привязан к окружению, дев — только синтетика."""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram-bot"))

from core import env as botkin_env_mod  # noqa: E402
from webhook.jwt_auth import generate_agent_jwt, get_agent_user  # noqa: E402

SECRET = "x" * 64
USER_ID = 111111


def _db_with_user():
    db = MagicMock()
    user = MagicMock(telegram_id=USER_ID, container_id="nc-test", jwt_secret=SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user
    return db


# ── core.env ────────────────────────────────────────────────────────────────


def test_env_defaults_to_local(monkeypatch):
    monkeypatch.delenv("BOTKIN_ENV", raising=False)
    assert botkin_env_mod.botkin_env() == "local"
    assert botkin_env_mod.jwt_issuer() == "botkin-local"
    assert botkin_env_mod.jwt_audience() == "botkin-agent-api-local"


def test_env_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("BOTKIN_ENV", "staging")
    with pytest.raises(RuntimeError):
        botkin_env_mod.botkin_env()


# ── JWT iss/aud ─────────────────────────────────────────────────────────────


def test_jwt_carries_env_claims(monkeypatch):
    monkeypatch.setenv("BOTKIN_ENV", "dev")
    token = generate_agent_jwt(USER_ID, "nc-test", SECRET)
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="botkin-agent-api-dev")
    assert claims["iss"] == "botkin-dev"
    assert claims["aud"] == "botkin-agent-api-dev"


@pytest.mark.asyncio
async def test_same_env_token_accepted(monkeypatch):
    monkeypatch.setenv("BOTKIN_ENV", "prod")
    token = generate_agent_jwt(USER_ID, "nc-test", SECRET)
    user = await get_agent_user(authorization=f"Bearer {token}", db=_db_with_user())
    assert user.telegram_id == USER_ID


@pytest.mark.asyncio
async def test_prod_token_rejected_on_dev_even_with_same_secret(monkeypatch):
    """Ровно сценарий F6: per-user секрет на деве совпал с продом."""
    monkeypatch.setenv("BOTKIN_ENV", "prod")
    prod_token = generate_agent_jwt(USER_ID, "nc-test", SECRET)
    monkeypatch.setenv("BOTKIN_ENV", "dev")
    with pytest.raises(HTTPException) as exc:
        await get_agent_user(authorization=f"Bearer {prod_token}", db=_db_with_user())
    assert exc.value.status_code == 401
    assert "another environment" in exc.value.detail


@pytest.mark.asyncio
async def test_token_without_env_claims_rejected(monkeypatch):
    """Старые токены без iss/aud больше не проходят."""
    monkeypatch.setenv("BOTKIN_ENV", "prod")
    legacy = jwt.encode(
        {
            "user_id": USER_ID,
            "container_id": "nc-test",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        await get_agent_user(authorization=f"Bearer {legacy}", db=_db_with_user())
    assert exc.value.status_code == 401


def test_in_process_agent_jwt_has_env_claims(monkeypatch):
    """core.agent_chat._generate_jwt выпускает токен, который проходит ту же проверку."""
    from core.agent_chat import _generate_jwt

    monkeypatch.setenv("BOTKIN_ENV", "dev")
    user = MagicMock(telegram_id=USER_ID, container_id=None, jwt_secret=SECRET)
    claims = jwt.decode(
        _generate_jwt(user), SECRET, algorithms=["HS256"], issuer="botkin-dev", audience="botkin-agent-api-dev"
    )
    assert claims["user_id"] == USER_ID


# ── Синтетический сид ───────────────────────────────────────────────────────


def _seed_module():
    sys.path.insert(0, str(ROOT / "scripts" / "dev"))
    import seed_synthetic

    return seed_synthetic


def test_seed_refuses_on_prod(monkeypatch, test_db):
    seed_synthetic = _seed_module()
    monkeypatch.setenv("BOTKIN_ENV", "prod")
    with pytest.raises(SystemExit):
        seed_synthetic.seed(test_db, users=1, days=3)
    with pytest.raises(SystemExit):
        seed_synthetic.reset(test_db)


def test_seed_creates_synthetic_users_with_fresh_secrets(monkeypatch, test_db):
    from database.models import BloodTest, NutritionLog, User, Weight

    seed_synthetic = _seed_module()
    monkeypatch.setenv("BOTKIN_ENV", "dev")
    report = seed_synthetic.seed(test_db, users=2, days=5, today=date(2026, 11, 9))

    assert len(report) == 2
    users = test_db.query(User).all()
    assert all(seed_synthetic.is_synthetic_id(u.telegram_id) for u in users)
    assert len({u.jwt_secret for u in users}) == 2
    assert all(u.health_token and u.share_token for u in users)
    uid = users[0].telegram_id
    assert test_db.query(NutritionLog).filter_by(user_id=uid).count() == 15
    assert test_db.query(Weight).filter_by(user_id=uid).count() == 5
    assert test_db.query(BloodTest).filter_by(user_id=uid).count() == 2
    meal = test_db.query(NutritionLog).filter_by(user_id=uid).first()
    assert "fats" in meal.totals and "fiber" in meal.totals

    # Повторный запуск добавляет новых, а не падает на занятых id.
    seed_synthetic.seed(test_db, users=1, days=2, today=date(2026, 11, 9))
    assert test_db.query(User).count() == 3


def test_seed_attach_and_reset_keep_real_dev_users(monkeypatch, test_db):
    from database.models import NutritionLog, User

    seed_synthetic = _seed_module()
    monkeypatch.setenv("BOTKIN_ENV", "dev")
    test_db.add(User(telegram_id=USER_ID, first_name="Dev"))
    test_db.commit()

    seed_synthetic.seed(test_db, attach=USER_ID, days=3, today=date(2026, 11, 9))
    assert test_db.query(NutritionLog).filter_by(user_id=USER_ID).count() == 9

    seed_synthetic.seed(test_db, users=1, days=2, today=date(2026, 11, 9))
    assert seed_synthetic.reset(test_db) == 1
    assert test_db.get(User, USER_ID) is not None
    assert test_db.query(User).count() == 1


def test_attach_unknown_user_fails(monkeypatch, test_db):
    seed_synthetic = _seed_module()
    monkeypatch.setenv("BOTKIN_ENV", "dev")
    with pytest.raises(SystemExit):
        seed_synthetic.seed(test_db, attach=424242, days=1)


# ── Регрессия: в репо нет пайплайна прод → дев ─────────────────────────────


def test_no_prod_to_dev_copy_in_repo():
    """Никакой скрипт/workflow не читает прод-БД или прод-data ради дева (ADR-0013)."""
    offenders = []
    for path in list((ROOT / "scripts").rglob("*")) + list((ROOT / ".github").rglob("*")):
        if not path.is_file() or path.suffix not in {".sh", ".py", ".yml", ".yaml"}:
            continue
        # Комментарии (примеры запуска вроде db_roles.sh) не считаем — ищем код.
        text = "\n".join(
            line for line in path.read_text(errors="ignore").splitlines() if not line.lstrip().startswith("#")
        )
        if ("healthvault_postgres" in text or "/opt/botkin/data" in text) and (
            "botkin_dev" in text or "/opt/botkin-dev" in text
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
