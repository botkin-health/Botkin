# tests/test_dashboard_biomarkers_db.py
import importlib.util
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "telegram-bot"))

spec = importlib.util.spec_from_file_location("dashboard_generator", ROOT / "telegram-bot" / "dashboard_generator.py")
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)


def test_load_biomarkers_from_db(test_db):
    test_db.execute(
        text(
            'INSERT INTO blood_tests (user_id, test_date, test_type, "values", status, created_at) '
            "VALUES (:u, :d, 'blood', :v, 'current', :c)"
        ),
        {"u": 999, "d": date(2025, 6, 1), "v": '{"ldl_mmol_l": 3.1}', "c": date(2025, 6, 1)},
    )
    test_db.commit()

    bio = dg._load_biomarkers_from_db(test_db, 999)
    assert bio["LDL"]["value"] == 3.1
    assert bio["LDL"]["date"] == "2025-06-01"
