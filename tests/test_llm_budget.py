"""Лимиты LLM: частота сообщений и дневной бюджет (пентест F15)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import llm_budget
from core.llm_budget import BudgetConfig, RateLimiter, check_llm_allowed
from database.models import Base

USER = 700001
OWNER = 700002


def _cfg(**kw) -> BudgetConfig:
    base = dict(
        enabled=True,
        rate_count=3,
        rate_window_sec=60,
        user_daily_usd=1.0,
        global_daily_usd=0.0,
        exempt_cohorts=frozenset({"owner"}),
    )
    base.update(kw)
    return BudgetConfig(**base)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("database.SessionLocal", Session)
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO users (telegram_id, cohort) VALUES (:a, 'external'), (:b, 'owner')"),
            {"a": USER, "b": OWNER},
        )
    llm_budget._reset_for_tests()
    yield engine
    llm_budget._reset_for_tests()


_ids = iter(range(1, 10_000))


def _spend(engine, user_id: int, usd: float, hours_ago: float = 1.0) -> None:
    # BigInteger PK в SQLite не автоинкрементится — id задаём сами
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO llm_usage_log (id, user_id, purpose, model, cost_usd, created_at) "
                "VALUES (:id, :u, 'agent_chat', 'claude-sonnet-5-5', :c, :ts)"
            ),
            {"id": next(_ids), "u": user_id, "c": usd, "ts": ts},
        )


# --- RateLimiter -------------------------------------------------------------


def test_rate_limiter_window():
    rl = RateLimiter()
    assert [rl.hit(1, 2, 60, now=t) for t in (0, 1)] == [0, 0]
    assert rl.hit(1, 2, 60, now=2) == 59  # первый слот освободится в t=60
    assert rl.hit(2, 2, 60, now=2) == 0  # другой пользователь независим
    assert rl.hit(1, 2, 60, now=60.5) == 0


def test_rejected_hits_are_not_counted():
    rl = RateLimiter()
    rl.hit(1, 1, 10, now=0)
    for t in range(1, 9):
        assert rl.hit(1, 1, 10, now=t) > 0
    assert rl.hit(1, 1, 10, now=10.1) == 0


# --- check_llm_allowed -------------------------------------------------------


def test_rate_limit_blocks_after_n_messages(db):
    cfg = _cfg()
    for _ in range(3):
        assert check_llm_allowed(USER, "external", cfg=cfg).allowed
    v = check_llm_allowed(USER, "external", cfg=cfg)
    assert not v.allowed and v.reason == "rate" and v.retry_after_sec > 0
    assert "Подожди" in v.user_message


def test_user_budget_over_24h(db):
    _spend(db, USER, 0.6, hours_ago=2)
    _spend(db, USER, 0.5, hours_ago=1)
    v = check_llm_allowed(USER, "external", cfg=_cfg())
    assert not v.allowed and v.reason == "user_budget"
    assert "22 ч" in v.user_message or "23 ч" in v.user_message


def test_old_spend_outside_window_ignored(db):
    _spend(db, USER, 5.0, hours_ago=25)
    _spend(db, USER, 0.2, hours_ago=1)
    assert check_llm_allowed(USER, "external", cfg=_cfg()).allowed


def test_owner_cohort_exempt(db):
    _spend(db, OWNER, 50.0)
    cfg = _cfg(rate_count=1)
    for _ in range(5):
        assert check_llm_allowed(OWNER, "owner", cfg=cfg).allowed


def test_cohort_looked_up_when_not_passed(db):
    _spend(db, OWNER, 50.0)
    assert check_llm_allowed(OWNER, cfg=_cfg()).allowed
    _spend(db, USER, 50.0)
    assert not check_llm_allowed(USER, cfg=_cfg()).allowed


def test_admin_exempt(db):
    _spend(db, USER, 50.0)
    with patch("config.users.is_admin", return_value=True):
        assert check_llm_allowed(USER, "external", cfg=_cfg()).allowed


def test_global_budget_counts_only_limited_users(db):
    _spend(db, OWNER, 100.0)  # owner не в счёт
    _spend(db, USER, 0.5)
    cfg = _cfg(user_daily_usd=10.0, global_daily_usd=1.0)
    assert check_llm_allowed(USER, "external", cfg=cfg).allowed
    llm_budget._reset_for_tests()  # сброс кэша глобальной суммы
    _spend(db, USER, 0.6)
    v = check_llm_allowed(USER, "external", cfg=cfg)
    assert not v.allowed and v.reason == "global_budget"


def test_disabled(db):
    _spend(db, USER, 50.0)
    assert check_llm_allowed(USER, "external", cfg=_cfg(enabled=False)).allowed


def test_fail_open_when_db_broken(monkeypatch):
    llm_budget._reset_for_tests()

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("database.SessionLocal", boom)
    assert check_llm_allowed(USER, "external", cfg=_cfg()).allowed


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_USER_DAILY_BUDGET_USD", "2.5")
    monkeypatch.setenv("LLM_RATE_LIMIT_COUNT", "7")
    monkeypatch.setenv("LLM_BUDGET_EXEMPT_COHORTS", "owner, family")
    monkeypatch.setenv("LLM_GLOBAL_DAILY_BUDGET_USD", "oops")
    cfg = BudgetConfig.from_env()
    assert cfg.user_daily_usd == 2.5 and cfg.rate_count == 7
    assert cfg.exempt_cohorts == {"owner", "family"}
    assert cfg.global_daily_usd == 40.0


# --- Middleware --------------------------------------------------------------


def _message(text_: str):
    from aiogram.types import Message

    msg = Message.model_construct(text=text_, from_user=SimpleNamespace(id=USER))
    return msg


def test_middleware_blocks_and_answers(monkeypatch):
    from middlewares import llm_guard

    v = llm_budget.Verdict(False, "rate", 30, "⏳ подожди")
    monkeypatch.setattr("core.llm_budget.check_llm_allowed", lambda uid, cohort: v)
    answer = AsyncMock()
    monkeypatch.setattr("aiogram.types.Message.answer", answer)
    handler = AsyncMock()

    asyncio.run(llm_guard.LlmGuardMiddleware()(handler, _message("съел борщ"), {"user_id": USER, "cohort": "external"}))
    handler.assert_not_called()
    answer.assert_awaited_once_with("⏳ подожди")


def test_middleware_passes_free_commands_and_allowed(monkeypatch):
    from middlewares import llm_guard

    calls = []

    def check(uid, cohort):
        calls.append(uid)
        return llm_budget.Verdict.ok()

    monkeypatch.setattr("core.llm_budget.check_llm_allowed", check)
    handler = AsyncMock(return_value="ok")
    mw = llm_guard.LlmGuardMiddleware()

    assert asyncio.run(mw(handler, _message("/start"), {"user_id": USER})) == "ok"
    assert calls == []  # /start не проверяется
    assert asyncio.run(mw(handler, _message("как мой сон?"), {"user_id": USER})) == "ok"
    assert calls == [USER]
