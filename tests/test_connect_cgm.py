"""Логика детекта нового пациента в /connect_cgm (#96)."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "telegram-bot" / "handlers" / "connect_cgm.py"
_spec = importlib.util.spec_from_file_location("connect_cgm_handler", _PATH)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def test_detect_new_patient_appeared():
    # Был один пациент, появился второй (его и привязываем).
    assert cc.detect_new_patient_ids({"A"}, ["A", "B"]) == ["B"]


def test_detect_nothing_new():
    assert cc.detect_new_patient_ids({"A", "B"}, ["A", "B"]) == []


def test_detect_from_empty_baseline():
    assert cc.detect_new_patient_ids(set(), ["X", "Y"]) == ["X", "Y"]
