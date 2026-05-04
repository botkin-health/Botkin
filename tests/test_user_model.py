import os
import sys
import importlib
import pytest

# Patch database package to avoid psycopg2 / Postgres connection at import time
# We only need database.models (pure SQLAlchemy ORM definitions), not the full package
import types

_fake_db_pkg = types.ModuleType("database")
sys.modules.setdefault("database", _fake_db_pkg)

# Now import models directly without triggering database/__init__.py
import importlib.util

_models_path = os.path.join(os.path.dirname(__file__), "..", "database", "models.py")
_spec = importlib.util.spec_from_file_location("database.models", _models_path)
_models_mod = importlib.util.module_from_spec(_spec)
sys.modules["database.models"] = _models_mod
_spec.loader.exec_module(_models_mod)

from database.models import User, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_user_has_cohort_field(db):
    u = User(telegram_id=999, first_name="Test", cohort="early_user", pack_name="cardiac")
    db.add(u)
    db.commit()
    fetched = db.query(User).filter_by(telegram_id=999).first()
    assert fetched.cohort == "early_user"
    assert fetched.pack_name == "cardiac"
    assert fetched.container_id is None  # nullable
    assert fetched.jwt_secret is None
