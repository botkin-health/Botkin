"""Security + характеризующий тест экранирования payload дашборда.

Дашборд встраивает JSON-payload в <script type="application/json">{{PAYLOAD}}.
В payload попадают пользовательские строки (display_name = first_name/username).
json.dumps НЕ экранирует '</' → строка вида '</script><script>...' закрывает
блок и исполняет инъекцию (stored XSS на /mc/{share_token}).

TDD: тест нацелен на чистый помощник `dashboard_generator._safe_payload_json`,
которого ещё нет (экранирование сейчас отсутствует — голый json.dumps на
строке 2570). Полный generate_dashboard_html на SQLite не гоняется (Postgres-
SQL), поэтому изолируем экранирование в чистую функцию.
RED сейчас (нет функции) → GREEN после фикса.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "telegram-bot"))

spec = importlib.util.spec_from_file_location("dashboard_generator", ROOT / "telegram-bot" / "dashboard_generator.py")
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)


def test_safe_payload_json_roundtrips_normal_data():
    """Характеризующий: обычные данные сериализуются и парсятся обратно без
    искажения (русские строки, числа, вложенность)."""
    payload = {"meta": {"display_name": "Иван", "age": 48}, "weight": [82.7, 83.1]}
    out = dg._safe_payload_json(payload)
    # После де-экранирования '<\/' → '</' это валидный JSON, равный исходнику.
    assert json.loads(out.replace("<\\/", "</")) == payload


def test_safe_payload_json_escapes_script_breakout():
    """Security: '</script>' в значении не остаётся сырым (нет XSS-брейкаута)."""
    attack = "</script><script>alert(document.cookie)</script>"
    payload = {"meta": {"display_name": attack}}
    out = dg._safe_payload_json(payload)
    assert "</script>" not in out, "сырой </script> в payload — XSS-брейкаут"
    assert "</" not in out, "последовательность '</' должна быть экранирована как '<\\/'"


def test_safe_payload_json_escapes_html_comment_open():
    """Security: '<!--' тоже экранируется (HTML-comment parser в <script>)."""
    payload = {"note": "x <!-- y"}
    out = dg._safe_payload_json(payload)
    assert "<!--" not in out
