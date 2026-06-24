"""Тесты сервиса генерации отчётов (in-memory SQLite, без реального дашборда)."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, HealthReport
from services.report_generator import (
    _build_diff_text,
    generate_and_save_report,
    get_report_by_token,
    get_report_token,
)

FAKE_HTML = "<html><body>report</body></html>"
FAKE_HTML_UPDATED = "<html><body>" + "x" * 5000 + "</body></html>"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _mock_dashboard(db_arg, user_id, embed=False):
    return FAKE_HTML


def _mock_dashboard_updated(db_arg, user_id, embed=False):
    return FAKE_HTML_UPDATED


class TestGenerateAndSaveReport:
    def test_first_call_creates_report(self, db):
        with patch("services.report_generator.generate_dashboard_html", _mock_dashboard):
            token, diff = generate_and_save_report(db, 12345)

        assert token is not None and len(token) > 10
        assert diff is None
        report = db.query(HealthReport).filter_by(user_id=12345).first()
        assert report is not None
        assert report.html == FAKE_HTML
        assert report.token == token

    def test_second_call_reuses_token(self, db):
        with patch("services.report_generator.generate_dashboard_html", _mock_dashboard):
            token1, _ = generate_and_save_report(db, 12345)
            token2, _ = generate_and_save_report(db, 12345)

        assert token1 == token2
        assert db.query(HealthReport).filter_by(user_id=12345).count() == 1

    def test_second_call_updates_html_and_returns_diff(self, db):
        with patch("services.report_generator.generate_dashboard_html", _mock_dashboard):
            generate_and_save_report(db, 12345)

        with patch("services.report_generator.generate_dashboard_html", _mock_dashboard_updated):
            _, diff = generate_and_save_report(db, 12345)

        report = db.query(HealthReport).filter_by(user_id=12345).first()
        assert report.html == FAKE_HTML_UPDATED
        assert diff == "данные обновлены"

    def test_different_users_get_different_tokens(self, db):
        with patch("services.report_generator.generate_dashboard_html", _mock_dashboard):
            token_a, _ = generate_and_save_report(db, 111)
            token_b, _ = generate_and_save_report(db, 222)

        assert token_a != token_b


class TestGetReportByToken:
    def test_returns_report_for_valid_token(self, db):
        db.add(HealthReport(user_id=99, token="abc123", html="<html/>"))
        db.commit()
        found = get_report_by_token(db, "abc123")
        assert found is not None and found.user_id == 99

    def test_returns_none_for_unknown_token(self, db):
        assert get_report_by_token(db, "unknown-token") is None


class TestGetReportToken:
    def test_returns_token_if_exists(self, db):
        db.add(HealthReport(user_id=77, token="tok777", html="<html/>"))
        db.commit()
        assert get_report_token(db, 77) == "tok777"

    def test_returns_none_if_no_report(self, db):
        assert get_report_token(db, 9999) is None


class TestBuildDiffText:
    def test_no_change_returns_none(self):
        report = HealthReport(user_id=1, token="t", html=FAKE_HTML)
        assert _build_diff_text(report, FAKE_HTML) is None

    def test_large_change_returns_diff(self):
        report = HealthReport(user_id=1, token="t", html=FAKE_HTML)
        assert _build_diff_text(report, FAKE_HTML_UPDATED) == "данные обновлены"

    def test_empty_html_returns_none(self):
        report = HealthReport(user_id=1, token="t", html="")
        assert _build_diff_text(report, FAKE_HTML) is None
