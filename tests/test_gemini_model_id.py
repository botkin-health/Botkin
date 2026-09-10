"""#440: id Gemini-модели — один на проект, из config/models.py, и не снятая с эксплуатации.

Прецедент 2026-09-10 (dev-стенд): все Gemini-вызовы падали с 404
«models/gemini-2.0-flash is no longer available. Please update your code to use
models/gemini-3.6-flash». id был зашит в config/models.py и ещё раз — прямо в
core/llm/router.py::analyze_message_gemini.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.models import VISION_MODEL_GEMINI, WEIGHT_OCR_MODEL_GEMINI  # noqa: E402

# Модели, которых по списку Google (проверено с prod-сервера 2026-09-10) больше нет.
RETIRED_GEMINI_MODELS = {"gemini-1.5-flash", "gemini-2.0-flash"}


def _fake_post(captured: list):
    def _post(url, *args, **kwargs):
        captured.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": '{"type": "other", "data": {}}'}]}}]}
        resp.raise_for_status.return_value = None
        return resp

    return _post


def test_configured_gemini_models_are_not_retired():
    assert VISION_MODEL_GEMINI not in RETIRED_GEMINI_MODELS
    assert WEIGHT_OCR_MODEL_GEMINI not in RETIRED_GEMINI_MODELS


def test_router_gemini_fallback_uses_configured_model():
    """analyze_message_gemini не должен хардкодить id — берёт из config/models.py."""
    from core.llm.router import analyze_message_gemini

    captured: list = []
    with (
        patch("core.llm.router._known_products_block", return_value=""),
        patch("core.llm.router.requests.post", side_effect=_fake_post(captured)),
        patch("core.llm.router.get_settings") as get_settings,
    ):
        get_settings.return_value = MagicMock(gemini_api_key="test-key", google_api_key=None)
        analyze_message_gemini(text="батончик", user_id=1)

    assert len(captured) == 1
    assert f"/models/{VISION_MODEL_GEMINI}:generateContent" in captured[0]
    assert not any(m in captured[0] for m in RETIRED_GEMINI_MODELS)


def test_gemini_vision_menu_parser_uses_configured_model(tmp_path):
    from core.vision.gemini_vision import parse_menu_with_gemini

    photo = tmp_path / "menu.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    captured: list = []
    with patch("core.vision.gemini_vision.requests.post", side_effect=_fake_post(captured)):
        parse_menu_with_gemini([photo], api_key="test-key")

    assert len(captured) == 1
    assert f"/models/{VISION_MODEL_GEMINI}:generateContent" in captured[0]
    assert not any(m in captured[0] for m in RETIRED_GEMINI_MODELS)
