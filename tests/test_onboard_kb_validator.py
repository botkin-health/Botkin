"""Валидация knowledge_base.json перед заливкой на сервер."""

import json

import pytest

from scripts.onboard.kb_validator import validate_kb, KbValidationError


def _write_kb(tmp_path, data):
    p = tmp_path / "knowledge_base.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


def test_valid_kb_passes(tmp_path):
    kb = {
        "blood_tests": [{"date": "2025-05-08", "values": {"vitamin_d": 35.4, "ferritin": 90}}],
        "diagnoses": ["J45 Asthma"],
    }
    p = _write_kb(tmp_path, kb)
    summary = validate_kb(p)
    assert summary.blood_tests_count == 1
    assert summary.size_bytes > 0


def test_kb_with_markers_field_raises(tmp_path):
    """Регрессия: standard_kb_values_field memory — должно быть 'values', не 'markers'."""
    kb = {"blood_tests": [{"date": "2025-05-08", "markers": {"vitamin_d": 35.4}}]}
    p = _write_kb(tmp_path, kb)
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "values" in str(exc.value)  # explain the standard


def test_kb_completely_empty_raises(tmp_path):
    """Нет ни анализов, ни ECG, ни диагнозов — заливать нечего."""
    p = _write_kb(tmp_path, {})
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "empty" in str(exc.value).lower() or "no data" in str(exc.value).lower()


def test_kb_too_large_raises(tmp_path):
    p = tmp_path / "huge.json"
    # 2 MB файл — над лимитом 1 MB
    p.write_text("{" + ('"x":"' + "a" * 1000 + '",') * 2100 + '"end":1}')
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "size" in str(exc.value).lower() or "large" in str(exc.value).lower()


def test_kb_invalid_json_raises(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json}")
    with pytest.raises(KbValidationError):
        validate_kb(p)


def test_kb_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_kb(tmp_path / "nonexistent.json")
