"""Валидация structure & sanity у knowledge_base.json перед заливкой."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_KB_SIZE_BYTES = 1_048_576  # 1 MB


class KbValidationError(ValueError):
    """KB не прошёл валидацию."""


@dataclass(frozen=True)
class KbSummary:
    size_bytes: int
    blood_tests_count: int
    medical_records_count: int
    diagnoses_count: int


def _check_no_markers_field(blood_tests: list[dict[str, Any]]) -> None:
    """Memory standard_kb_values_field: биомаркеры идут в 'values', не 'markers'.

    Если запись содержит ОБА поля (`markers` и `values`) — это транзитивное
    состояние миграции, пропускаем без ошибки. Только legacy-формат (только
    `markers`, нет `values`) триггерит KbValidationError.
    """
    for i, bt in enumerate(blood_tests):
        # Both fields present = transitional migration state, allowed through
        if "markers" in bt and "values" not in bt:
            raise KbValidationError(
                f"blood_tests[{i}] uses legacy field 'markers' — must be 'values' "
                f"(see memory: standard_kb_values_field). Migrate the KB first."
            )


def validate_kb(path: Path) -> KbSummary:
    """Прочитать и проверить KB. Вернуть summary либо бросить KbValidationError."""
    if not path.exists():
        raise FileNotFoundError(f"KB not found: {path}")

    size = path.stat().st_size
    if size > MAX_KB_SIZE_BYTES:
        raise KbValidationError(
            f"KB too large: {size} bytes > {MAX_KB_SIZE_BYTES} limit. "
            "Likely a parsing bug — investigate before uploading."
        )

    try:
        kb = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KbValidationError(f"KB is not valid JSON: {e}") from e

    for field in ("blood_tests", "medical_records", "ecg", "diagnoses"):
        val = kb.get(field)
        if val is not None and not isinstance(val, list):
            raise KbValidationError(
                f"KB field {field!r} must be a list, got {type(val).__name__}. "
                "KB schema error — fix the KB before uploading."
            )

    blood_tests = kb.get("blood_tests", []) or []
    medical_records = kb.get("medical_records", []) or []
    ecg = kb.get("ecg", []) or []
    diagnoses = kb.get("diagnoses", []) or []

    if not (blood_tests or medical_records or ecg or diagnoses):
        raise KbValidationError("KB is empty — no blood_tests/medical_records/ecg/diagnoses. Nothing to upload.")

    _check_no_markers_field(blood_tests)

    return KbSummary(
        size_bytes=size,
        blood_tests_count=len(blood_tests),
        medical_records_count=len(medical_records),
        diagnoses_count=len(diagnoses),
    )
