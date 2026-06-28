# tests/test_doc_extractor.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_extract_returns_dict_on_success():
    """Экстрактор возвращает dict с date/laboratory/values при валидном ответе Claude."""
    mock_response = {
        "content": [{"type": "text", "text": json.dumps({
            "date": "2026-04-13",
            "laboratory": "KDL",
            "values": {"Hb": 165, "ferritin": 112}
        })}]
    }
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data
        result = await extract_medical_data(b"fake-pdf-bytes", "application/pdf")
    assert result["date"] == "2026-04-13"
    assert result["values"]["Hb"] == 165


@pytest.mark.asyncio
async def test_extract_returns_empty_dict_when_no_values_found():
    """Экстрактор возвращает {} если Claude ничего не нашёл."""
    mock_response = {
        "content": [{"type": "text", "text": "{}"}]
    }
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data
        result = await extract_medical_data(b"fake-bytes", "image/jpeg")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_handles_malformed_json_gracefully():
    """Если Claude вернул не-JSON — возвращаем {}, не падаем."""
    mock_response = {
        "content": [{"type": "text", "text": "Я не нашёл ничего в документе."}]
    }
    with patch("core.health.doc_extractor._call_anthropic", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        from core.health.doc_extractor import extract_medical_data
        result = await extract_medical_data(b"fake-bytes", "image/jpeg")
    assert result == {}
