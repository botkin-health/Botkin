"""Сервис генерации и хранения HTML-отчётов пользователей (#203).

Отчёт = полный дашборд (generate_dashboard_html), сохранённый в health_reports.
Каждый пользователь имеет одну запись — при повторном вызове HTML обновляется,
токен остаётся прежним (URL не меняется).
"""

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from database.models import HealthReport


def _ensure_bot_path() -> None:
    """Добавить telegram-bot/ в sys.path если ещё нет (dashboard_generator живёт там)."""
    import sys
    from pathlib import Path

    bot_dir = Path(__file__).resolve().parent.parent / "telegram-bot"
    if str(bot_dir) not in sys.path:
        sys.path.insert(0, str(bot_dir))


def generate_dashboard_html(db: Session, telegram_id: int, embed: bool = False) -> str:
    """Тонкая обёртка над dashboard_generator.generate_dashboard_html для мокирования в тестах."""
    _ensure_bot_path()
    from dashboard_generator import generate_dashboard_html as _gen

    return _gen(db, telegram_id, embed=embed)


def generate_and_save_report(db: Session, telegram_id: int) -> tuple[str, Optional[str]]:
    """Сгенерировать HTML-отчёт и сохранить в health_reports.

    Возвращает (token, diff_text):
    - token — публичный токен для URL /r/{token}
    - diff_text — краткое описание изменений если это обновление, иначе None
    """
    html = generate_dashboard_html(db, telegram_id, embed=False)

    existing = db.query(HealthReport).filter_by(user_id=telegram_id).first()

    if existing is None:
        token = secrets.token_urlsafe(32)
        report = HealthReport(user_id=telegram_id, token=token, html=html)
        db.add(report)
        db.commit()
        return token, None

    diff_text = _build_diff_text(existing, html)
    existing.html = html
    existing.updated_at = datetime.now(timezone.utc)
    db.commit()
    return existing.token, diff_text


def get_report_by_token(db: Session, token: str) -> Optional[HealthReport]:
    return db.query(HealthReport).filter_by(token=token).first()


def get_report_token(db: Session, telegram_id: int) -> Optional[str]:
    """Вернуть токен существующего отчёта или None."""
    report = db.query(HealthReport).filter_by(user_id=telegram_id).first()
    return report.token if report else None


def _build_diff_text(existing: HealthReport, new_html: str) -> Optional[str]:
    """Краткий diff: есть ли смысл сообщать об обновлении.

    Сравниваем только по размеру HTML — точный diff контента слишком тяжёл.
    Если разница > 1% — считаем что данные обновились.
    """
    old_len = len(existing.html)
    new_len = len(new_html)
    if old_len == 0:
        return None
    if abs(new_len - old_len) / old_len > 0.01:
        return "данные обновлены"
    return None
