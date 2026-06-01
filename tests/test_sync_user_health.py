# tests/test_sync_user_health.py
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.users import KB_USERS


def test_kb_users_has_all_seven():
    assert len(KB_USERS) == 7
    assert KB_USERS[895655].startswith("Александр")


def test_sync_user_health_importable_and_has_main():
    spec = importlib.util.spec_from_file_location("sync_user_health", ROOT / "scripts" / "sync_user_health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")
    assert hasattr(mod, "sync_user")
