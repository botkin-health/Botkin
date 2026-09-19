"""Regression #474: сборка workouts_log не должна молча писать файл «для юзера 0».

Имя файла содержит telegram_id, и читатели (агент `/recent_workouts`, дашборд)
ищут строго по нему. Пустая переменная окружения превращала id в 0 — файл уезжал
в workouts_log_0.json, скрипт завершался успешно, а агент месяц отвечал из
обеднённого DB-фолбэка без пульса и зон.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "util" / "build_workouts_log.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_workouts_log", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_workouts_log"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_workouts_log():
    return _load_module()


def test_zero_user_id_aborts_with_actionable_message(build_workouts_log):
    with pytest.raises(SystemExit) as exc:
        build_workouts_log.validate_user_id(0)
    message = str(exc.value)
    assert "BOTKIN_USER_ID" in message
    assert "--user-id" in message


def test_negative_user_id_aborts(build_workouts_log):
    with pytest.raises(SystemExit):
        build_workouts_log.validate_user_id(-1)


def test_real_user_id_passes(build_workouts_log):
    assert build_workouts_log.validate_user_id(123456789) is None


def test_out_path_carries_user_id(build_workouts_log):
    assert build_workouts_log.out_path_for(123456789).name == "workouts_log_123456789.json"
