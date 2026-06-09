"""Tests for P-003 — авто-инвалидация устаревших turn'ов истории агента.

Прецедент 09.06.2026: после фикса Z2-метрики тул отдаёт правильные числа
(106 мин/нед, пробежка 36.7 мин), но агент в Telegram продолжал парротить
старые числа (61/38) и «Z2=0/баг» из накопленной истории, игнорируя свежий
tool_result. Промпт-правило (ad73abf) оказалось недостаточным.

`_invalidate_stale_history` ПЕРЕД отправкой истории в Claude сравнивает
ключевые числа свежего tool_result текущего хода с числами/утверждениями в
недавних assistant-turn'ах истории и при явном конфликте нейтрализует
устаревший turn. См. docs/night-shift/2026-06-09.md (P-003).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import json

from core.agent_chat import _invalidate_stale_history


# Свежий tool_result get_recent_workouts (как его видит Claude): aerobic base
# 106 мин/нед, пробежка 36.7 мин. Это ground truth текущего хода.
FRESH_WORKOUTS = json.dumps(
    {
        "source": "file",
        "stats": {
            "per_week": 3.5,
            "z2_min_per_week": 106,
            "hiit_min_per_week": 12,
            "z2_target_attia": 150,
        },
        "items": [
            {
                "type": "running",
                "name": "Москва - База",
                "distance_km": 6.2,
                "duration_min": 41.0,
                "aerobic_base_min": 36.7,
            },
            {"type": "strength_training", "name": "Зал", "duration_min": 50.0, "aerobic_base_min": 0},
        ],
    },
    ensure_ascii=False,
)


def _assistant_turn(text: str) -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _turn_text(msg: dict) -> str:
    return " ".join(b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text")


def test_stale_numeric_z2_turn_is_neutralized():
    """Старый turn с «61 мин/нед» и «38 мин» Z2 → нейтрализуется, число исчезает."""
    messages = [
        {"role": "user", "content": "сколько Z2 за неделю?"},
        _assistant_turn("Твоя Z2-база — 61 мин/нед, последняя пробежка в Z2 заняла 38 мин."),
    ]
    notes = _invalidate_stale_history(messages, FRESH_WORKOUTS)

    assert notes, "ожидался хотя бы один лог об инвалидации"
    stale = _turn_text(messages[1])
    assert "61" not in stale
    assert "38" not in stale
    assert "устаревш" in stale.lower() or "P-003" in stale


def test_bug_zero_claim_is_neutralized_when_fresh_positive():
    """Старый turn «Z2 = 0, это баг» → нейтрализуется, т.к. свежий Z2 > 0."""
    messages = [
        _assistant_turn("Похоже, Z2 у тебя 0 мин — это баг, метрика не считается."),
    ]
    notes = _invalidate_stale_history(messages, FRESH_WORKOUTS)

    assert notes
    stale = _turn_text(messages[0])
    assert "баг" not in stale.lower()


def test_turn_with_matching_fresh_number_is_kept():
    """Консервативность: turn, цитирующий актуальное число (36.7) — НЕ трогаем."""
    keep = "Последняя пробежка в Z2 — 36.7 мин, аэробная база 106 мин/нед."
    messages = [_assistant_turn(keep)]
    notes = _invalidate_stale_history(messages, FRESH_WORKOUTS)

    assert notes == []
    assert _turn_text(messages[0]) == keep


def test_turn_without_metric_keyword_is_kept():
    """Консервативность: turn про другую метрику (вес) не трогаем при Z2-tool."""
    keep = "Твой вес сегодня 82.4 кг, давление 120/80."
    messages = [_assistant_turn(keep)]
    notes = _invalidate_stale_history(messages, FRESH_WORKOUTS)

    assert notes == []
    assert _turn_text(messages[0]) == keep


def test_mixed_turn_with_one_current_number_is_kept():
    """Регрессия на дробление сегментов (verify 09.06): turn «Z2-база — 61 мин/нед,
    пробежка 38 мин», где 61 = актуальное недельное число, НЕ инвалидируется —
    keyword «Z2» не должен отрываться от «61» при разбиении « — »/«, »."""
    fresh = json.dumps(
        {
            "stats": {"z2_min_per_week": 61, "z2_target_attia": 150},
            "items": [{"aerobic_base_min": 18.5, "duration_min": 49.6}],
        },
        ensure_ascii=False,
    )
    keep = "Твоя Z2-база — 61 мин/нед, последняя пробежка в Z2 заняла 38 мин."
    messages = [_assistant_turn(keep)]
    notes = _invalidate_stale_history(messages, fresh)

    assert notes == [], "turn содержит актуальное число 61 — не трогаем"
    assert _turn_text(messages[0]) == keep


def test_rounding_within_tolerance_is_kept():
    """Консервативность: «37 мин» (округление 36.7) не считается конфликтом."""
    keep = "Последняя пробежка в Z2 заняла 37 мин."
    messages = [_assistant_turn(keep)]
    notes = _invalidate_stale_history(messages, FRESH_WORKOUTS)

    assert notes == []
    assert _turn_text(messages[0]) == keep
