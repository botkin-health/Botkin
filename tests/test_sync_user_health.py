# tests/test_sync_user_health.py
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.users import KB_USERS


def test_kb_users_is_dict():
    # KB_USERS подгружается из приватного config/users_private.py (в .gitignore),
    # с fallback на {} в публичном репозитории. Поэтому проверяем структуру (это dict),
    # а не конкретный состав/количество пользователей — оно зависит от приватного конфига.
    assert isinstance(KB_USERS, dict)


def test_sync_user_health_importable_and_has_main():
    spec = importlib.util.spec_from_file_location("sync_user_health", ROOT / "scripts" / "sync_user_health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")
    assert hasattr(mod, "sync_user")
