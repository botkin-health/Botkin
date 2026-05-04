import pytest
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_session():
    """Connection as admin role (healthvault) — bypasses RLS, triggers audit."""
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


def test_admin_insert_logged(admin_session):
    """Admin INSERT on nutrition_log triggers audit_log entry."""
    before = admin_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE table_name='nutrition_log'")).scalar()

    # Insert a test row (we'll clean it up)
    admin_session.execute(
        text(
            "INSERT INTO nutrition_log (user_id, date, meal_time, items, totals) "
            "VALUES (895655, CURRENT_DATE, CURRENT_TIME, '[]'::jsonb, '{}'::jsonb)"
        )
    )
    admin_session.commit()

    after = admin_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE table_name='nutrition_log'")).scalar()
    assert after == before + 1

    # Verify content
    last = admin_session.execute(
        text("SELECT db_user, query_type, table_name FROM audit_log ORDER BY ts DESC LIMIT 1")
    ).first()
    assert last.db_user == "healthvault"
    assert last.query_type == "INSERT"
    assert last.table_name == "nutrition_log"
