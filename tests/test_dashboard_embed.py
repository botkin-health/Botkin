"""Тест embed-режима дашборда (scale-to-fit в мини-аппе) — issue #143.

Вкладка «Здоровье» мини-аппа встраивает /mc/{token} в iframe. Десктоп-шаблон
зафиксирован на viewport=1440 → на телефоне обрезан. Фикс: embed-режим
(?embed=1) подставляет class="embed" + device-width viewport, шаблон ужимает
1440px-вёрстку через zoom.

Полный generate_dashboard_html на SQLite не гоняется (Postgres-SQL), поэтому
подстановку placeholder'ов изолируем в чистую `_apply_embed_mode` (как
`_safe_payload_json` в test_dashboard_xss.py) и проверяем её против реального
шаблона.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "telegram-bot"))

spec = importlib.util.spec_from_file_location("dashboard_generator", ROOT / "telegram-bot" / "dashboard_generator.py")
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)

TEMPLATE = (ROOT / "telegram-bot" / "mc_template.html").read_text(encoding="utf-8")


def test_embed_mode_adds_class_and_device_width_viewport():
    """embed=True: <html> получает class="embed", viewport — device-width."""
    out = dg._apply_embed_mode(TEMPLATE, embed=True)
    assert '<html lang="ru" class="embed">' in out
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in out


def test_desktop_mode_keeps_1440_viewport_and_no_embed_class():
    """embed=False: десктоп-вёрстка не меняется — нет класса, viewport=1440."""
    out = dg._apply_embed_mode(TEMPLATE, embed=False)
    assert '<html lang="ru">' in out
    # тег <html> без embed-класса (подстрока class="embed" есть в комментарии JS — её не ловим)
    assert '<html lang="ru" class="embed">' not in out
    assert '<meta name="viewport" content="width=1440">' in out


def test_no_unresolved_placeholders_in_either_mode():
    """Оба режима резолвят placeholder'ы шаблона — ни {{HTML_CLASS}}, ни {{VIEWPORT}}
    не утекают в выдачу (страж синхронизации шаблона и помощника)."""
    for embed in (True, False):
        out = dg._apply_embed_mode(TEMPLATE, embed=embed)
        assert "{{HTML_CLASS}}" not in out
        assert "{{VIEWPORT}}" not in out
