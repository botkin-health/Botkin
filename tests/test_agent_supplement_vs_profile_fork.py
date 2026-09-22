"""Тесты #507: приём лекарства уходил в медпрофиль (save_health_profile) вместо
supplements_log — событие приёма терялось целиком, хотя пользователь получал
осмысленный ответ и считал, что приём записан.

Развилка «разовое событие приёма» vs «факт о постоянной терапии» нигде не была
описана явно — ни в описаниях тулов, ни в системном промпте. Тесты фиксируют
формулировки, которые эту развилку описывают, по образцу test_agent_chrono_tools.py
(схема/описание тула) и test_doc_extractor.py (текст промпта через inspect.getsource).
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.agent_chat as agent_chat


def _tool(name):
    return next(t for t in agent_chat.TOOLS if t["name"] == name)


# ── save_health_profile НЕ должен маскировать разовый приём ─────────────────


def test_save_health_profile_description_excludes_single_event():
    desc = _tool("save_health_profile")["description"]
    assert "log_supplement" in desc
    assert "разовый приём" in desc or "СОБЫТИЕ" in desc


def test_save_health_profile_description_no_longer_lists_bare_medication_trigger():
    """Раньше «постоянное лекарство» в триггерах читалось как «любое упоминание
    лекарства» — модель путала разовый приём с постоянной терапией (#507)."""
    desc = _tool("save_health_profile")["description"]
    assert "постоянное состояние" in desc or "ПОСТОЯННОЕ" in desc


# ── log_supplement явно про событие, включая пропуски доз в прошлом ─────────


def test_log_supplement_description_covers_missed_dose_in_past():
    desc = _tool("log_supplement")["description"]
    assert "пропуск" in desc.lower()
    assert "save_health_profile" in desc


def test_log_supplement_description_still_has_date_time_guidance():
    """Не конфликтуем с фиксом #502 (даты для log_supplement/log_bp)."""
    desc = _tool("log_supplement")["description"]
    assert "`date`/`time`" in desc


# ── Явный текст развилки в системном промпте ────────────────────────────────


def test_system_prompt_has_explicit_fork_section():
    src = inspect.getsource(agent_chat)
    assert "РАЗВИЛКА: приём или медпрофиль" in src


def test_system_prompt_fork_mentions_both_tools_for_mixed_phrase():
    src = inspect.getsource(agent_chat)
    assert "log_supplement" in src
    assert "save_health_profile" in src
    assert "ОБА тула" in src


def test_system_prompt_fork_forbids_replacing_event_with_profile():
    """Суть развилки: запись события нельзя подменить записью в медпрофиль —
    именно так терялся приём («капотен несколько дней назад», #507)."""
    src = inspect.getsource(agent_chat)
    assert "заменять запись события записью в профиль нельзя" in src


def test_system_prompt_fork_instructs_ask_when_ambiguous():
    """DoD п.3: при неоднозначности агент должен переспросить, а не выбрать молча."""
    src = inspect.getsource(agent_chat)
    assert "переспроси" in src
