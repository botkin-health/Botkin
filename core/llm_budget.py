"""
Лимиты на LLM для пользователя: частота сообщений и бюджет в долларах за 24 часа.

Зачем (пентест 08.11.2026, F15): регистрация открыта, и любое сообщение уходит в
Claude без ограничений — один пользователь или скрипт может сжечь бюджет API.

Три уровня, все настраиваются через env:
    LLM_RATE_LIMIT_COUNT / LLM_RATE_LIMIT_WINDOW_SEC
        не больше N сообщений, идущих в LLM, за окно (по умолчанию 20 за 300 с).
        Счётчик в памяти процесса — бот работает одним процессом.
    LLM_USER_DAILY_BUDGET_USD
        сколько стоят вызовы пользователя за последние 24 часа по llm_usage_log
        (по умолчанию $3; реальный максимум за сентябрь–ноябрь 2026 — $1.38).
    LLM_GLOBAL_DAILY_BUDGET_USD
        общий расход всех нелимитных пользователей за 24 часа — аварийный стоп
        на случай волны регистраций (по умолчанию $40, 0 — выключить).

Без лимитов: админы (BOTKIN_ADMIN_IDS) и когорты из LLM_BUDGET_EXEMPT_COHORTS
(по умолчанию «owner»). LLM_BUDGET_ENABLED=0 выключает всё.

Окно бюджета скользящее (24 часа назад от текущего момента), а не календарный
день: не зависит от часового пояса пользователя.

Бюджет проверяется до вызова, расход пишется после, поэтому одно сообщение может
превысить лимит на свою стоимость (агент ограничен MAX_TOOL_ITERATIONS=6 раундами).
Если БД недоступна, проверка бюджета пропускается (fail-open): ограничение
частоты всё равно работает, а падать на каждом сообщении из-за учёта нельзя.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_WINDOW_24H = timedelta(hours=24)
_GLOBAL_CACHE_TTL_SEC = 60.0


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("llm_budget: %s=%r не число, беру %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass(frozen=True)
class BudgetConfig:
    enabled: bool
    rate_count: int
    rate_window_sec: int
    user_daily_usd: float
    global_daily_usd: float
    exempt_cohorts: frozenset[str]

    @classmethod
    def from_env(cls) -> "BudgetConfig":
        cohorts = os.getenv("LLM_BUDGET_EXEMPT_COHORTS", "owner")
        return cls(
            enabled=os.getenv("LLM_BUDGET_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off"),
            rate_count=_env_int("LLM_RATE_LIMIT_COUNT", 20),
            rate_window_sec=_env_int("LLM_RATE_LIMIT_WINDOW_SEC", 300),
            user_daily_usd=_env_float("LLM_USER_DAILY_BUDGET_USD", 3.0),
            global_daily_usd=_env_float("LLM_GLOBAL_DAILY_BUDGET_USD", 40.0),
            exempt_cohorts=frozenset(c.strip() for c in cohorts.split(",") if c.strip()),
        )


@dataclass(frozen=True)
class Verdict:
    """Результат проверки. allowed=False — в LLM не ходить, показать user_message."""

    allowed: bool
    reason: str = ""  # "rate" | "user_budget" | "global_budget"
    retry_after_sec: int = 0
    user_message: str = ""

    @classmethod
    def ok(cls) -> "Verdict":
        return cls(True)


# ---------------------------------------------------------------------------
# Частота: скользящее окно в памяти
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, user_id: int, limit: int, window_sec: int, now: Optional[float] = None) -> int:
        """Учесть обращение. 0 — можно; иначе через сколько секунд освободится слот.

        Отклонённое обращение не учитывается: иначе пользователь, который
        продолжает писать, никогда не выйдет из-под лимита.
        """
        if limit <= 0 or window_sec <= 0:
            return 0
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(user_id, deque())
            while q and q[0] <= now - window_sec:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(q[0] + window_sec - now) + 1)
            q.append(now)
            if len(self._hits) > 10_000:  # не копить память на тысячах разовых юзеров
                for uid in [u for u, d in self._hits.items() if not d or d[-1] <= now - window_sec]:
                    del self._hits[uid]
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_rate_limiter = RateLimiter()
_global_cache: dict[str, float] = {}  # {"value": usd, "at": monotonic}
_global_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Деньги: llm_usage_log
# ---------------------------------------------------------------------------


def _since(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - _WINDOW_24H


def user_spend_24h(db, user_id: int, now: Optional[datetime] = None) -> float:
    from sqlalchemy import text

    row = db.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage_log WHERE user_id = :uid AND created_at >= :since"),
        {"uid": user_id, "since": _since(now)},
    ).scalar()
    return float(row or 0)


def oldest_user_spend_24h(db, user_id: int, now: Optional[datetime] = None) -> Optional[datetime]:
    from sqlalchemy import text

    return db.execute(
        text("SELECT MIN(created_at) FROM llm_usage_log WHERE user_id = :uid AND created_at >= :since"),
        {"uid": user_id, "since": _since(now)},
    ).scalar()


def limited_spend_24h(db, exempt_cohorts: frozenset[str], now: Optional[datetime] = None) -> float:
    """Расход всех пользователей с лимитом (не из exempt-когорт) за 24 часа."""
    from sqlalchemy import bindparam, text

    sql = (
        "SELECT COALESCE(SUM(l.cost_usd), 0) FROM llm_usage_log l "
        "JOIN users u ON u.telegram_id = l.user_id "
        "WHERE l.created_at >= :since"
    )
    params: dict = {"since": _since(now)}
    if exempt_cohorts:
        sql += " AND u.cohort NOT IN :cohorts"
        params["cohorts"] = list(exempt_cohorts)
        stmt = text(sql).bindparams(bindparam("cohorts", expanding=True))
    else:
        stmt = text(sql)
    return float(db.execute(stmt, params).scalar() or 0)


def _cached_global_spend(db, cfg: BudgetConfig) -> float:
    now = time.monotonic()
    with _global_lock:
        if _global_cache and now - _global_cache["at"] < _GLOBAL_CACHE_TTL_SEC:
            return _global_cache["value"]
    value = limited_spend_24h(db, cfg.exempt_cohorts)
    with _global_lock:
        _global_cache.update(value=value, at=now)
    return value


def _hours_until(ts: "Optional[datetime | str]", now: Optional[datetime] = None) -> int:
    if ts is None:
        return 24
    if isinstance(ts, str):  # SQLite (тесты) отдаёт MIN() строкой
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:  # SQLite в тестах отдаёт naive
        ts = ts.replace(tzinfo=timezone.utc)
    left = ts + _WINDOW_24H - (now or datetime.now(timezone.utc))
    return max(1, int(left.total_seconds() // 3600) + 1)


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


def is_exempt(user_id: int, cohort: Optional[str], cfg: Optional[BudgetConfig] = None) -> bool:
    cfg = cfg or BudgetConfig.from_env()
    try:
        from config.users import is_admin

        if is_admin(int(user_id)):
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(cohort) and cohort in cfg.exempt_cohorts


def _lookup_cohort(db, user_id: int) -> Optional[str]:
    from sqlalchemy import text

    return db.execute(text("SELECT cohort FROM users WHERE telegram_id = :uid"), {"uid": user_id}).scalar()


def check_llm_allowed(
    user_id: int,
    cohort: Optional[str] = None,
    *,
    count_hit: bool = True,
    cfg: Optional[BudgetConfig] = None,
) -> Verdict:
    """Можно ли этому пользователю сейчас идти в LLM.

    count_hit=True учитывает обращение в ограничителе частоты (одно сообщение —
    один вызов). Открывает свою короткую сессию БД и закрывает её до возврата —
    транзакция не висит поперёк последующего вызова LLM.
    """
    cfg = cfg or BudgetConfig.from_env()
    if not cfg.enabled:
        return Verdict.ok()

    db = None
    try:
        # Учёт трат — явный межпользовательский путь (общий потолок суммирует всех),
        # поэтому сессия без RLS. Под рантайм-ролью hv_app обычная сессия видела бы
        # только строки текущего пользователя, а без контекста — ноль, и лимит
        # молча не срабатывал бы (ADR-0014).
        from database import system_session

        db = system_session()
        if cohort is None:
            cohort = _lookup_cohort(db, user_id)
        if is_exempt(user_id, cohort, cfg):
            return Verdict.ok()

        if count_hit:
            wait = _rate_limiter.hit(user_id, cfg.rate_count, cfg.rate_window_sec)
            if wait:
                return Verdict(
                    False,
                    "rate",
                    wait,
                    f"⏳ Слишком много сообщений подряд. Подожди {_fmt_wait(wait)} и пришли ещё раз.",
                )

        try:
            if cfg.user_daily_usd > 0:
                spent = user_spend_24h(db, user_id)
                if spent >= cfg.user_daily_usd:
                    hours = _hours_until(oldest_user_spend_24h(db, user_id))
                    logger.warning(
                        "llm_budget: user %s hit daily budget (%.2f >= %.2f USD)", user_id, spent, cfg.user_daily_usd
                    )
                    return Verdict(
                        False,
                        "user_budget",
                        hours * 3600,
                        "🌙 На сегодня лимит запросов к AI исчерпан. "
                        f"Он восстановится примерно через {hours} ч. Записи по кнопкам и дашборд работают как обычно.",
                    )
            if cfg.global_daily_usd > 0:
                total = _cached_global_spend(db, cfg)
                if total >= cfg.global_daily_usd:
                    logger.error("llm_budget: GLOBAL daily budget hit (%.2f >= %.2f USD)", total, cfg.global_daily_usd)
                    return Verdict(
                        False,
                        "global_budget",
                        3600,
                        "⚠️ AI сейчас перегружен, попробуй через час. Мы уже разбираемся.",
                    )
        except Exception:  # noqa: BLE001 — учёт не должен ронять бота
            logger.exception("llm_budget: budget query failed for user %s, fail-open", user_id)
        return Verdict.ok()
    except Exception:  # noqa: BLE001
        logger.exception("llm_budget: check failed for user %s, fail-open", user_id)
        return Verdict.ok()
    finally:
        if db is not None:
            try:
                db.rollback()
            finally:
                db.close()


def _fmt_wait(sec: int) -> str:
    if sec < 60:
        return f"{sec} с"
    return f"{(sec + 59) // 60} мин"


def _reset_for_tests() -> None:
    _rate_limiter.reset()
    with _global_lock:
        _global_cache.clear()
