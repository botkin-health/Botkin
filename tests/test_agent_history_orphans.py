"""_validate_history: окно истории никогда не начинается с осиротевшего tool_result.

Прецедент 28.09.2026 (dev, user 895655): окно HISTORY_WINDOW=20 начиналось с
tool_result (id 1835), чей tool_use остался за границей окна. Валидатор вырезал
его, затем выкинул ведущее assistant-сообщение (thinking + tool_use из 1836) —
и tool_result этого tool_use (1837) становился новой сиротой в messages[0].
Anthropic отвечал 400, ask_agent ретраил с пустой историей.
"""

from core.agent_chat import _validate_history


def _tool_use(tid):
    return {"type": "tool_use", "id": tid, "name": "get_activities", "input": {}}


def _tool_result(tid):
    return {"type": "tool_result", "tool_use_id": tid, "content": "{}"}


def _thinking():
    return {"type": "thinking", "thinking": "", "signature": "sig"}


def _text(t):
    return {"type": "text", "text": t}


def _all_ids(messages, btype, key):
    return [b[key] for m in messages if isinstance(m["content"], list) for b in m["content"] if b.get("type") == btype]


def _assert_api_valid(messages):
    assert messages, "история не должна пропадать целиком"
    assert messages[0]["role"] == "user"
    first = messages[0]["content"]
    if isinstance(first, list):
        assert any(b.get("type") != "tool_result" for b in first), "первое сообщение — только tool_result"
    # Каждый tool_result ссылается на tool_use из непосредственно предыдущего сообщения.
    for i, m in enumerate(messages):
        if not isinstance(m["content"], list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_result":
                prev = messages[i - 1] if i > 0 else None
                assert prev and prev["role"] == "assistant"
                assert b["tool_use_id"] in {x.get("id") for x in prev["content"] if x.get("type") == "tool_use"}


def test_window_starting_mid_tool_loop_is_trimmed_to_user_turn():
    # Точное окно dev: 1835 (сирота) … 1854, уже после перегруппировки _load_history.
    messages = [
        {"role": "user", "content": [_tool_result("W2E")]},  # 1835, tool_use за окном
        {"role": "assistant", "content": [_thinking(), _tool_use("Kgi")]},  # 1836
        {"role": "user", "content": [_tool_result("Kgi")]},  # 1837
        {"role": "assistant", "content": [_text("смотрю"), _tool_use("KuH")]},  # 1838
        {"role": "user", "content": [_tool_result("KuH")]},  # 1839
        {"role": "assistant", "content": [_text("ответ 1")]},  # 1840
        {"role": "user", "content": "вопрос 2"},  # 1841
        {"role": "assistant", "content": [_tool_use("A7e")]},
        {"role": "user", "content": [_tool_result("A7e")]},
        {"role": "assistant", "content": [_text("ответ 2")]},
        {"role": "user", "content": "вопрос 3"},  # 1845
        {"role": "assistant", "content": [_thinking(), _tool_use("AuT")]},
        {"role": "user", "content": [_tool_result("AuT")]},
        {"role": "assistant", "content": [_text("ответ 3")]},
    ]
    cleaned = _validate_history(messages)
    _assert_api_valid(cleaned)
    assert "Kgi" not in _all_ids(cleaned, "tool_result", "tool_use_id")
    assert cleaned[0] == {"role": "user", "content": "вопрос 2"}
    # Полные ходы сохранены, а не выброшены вместе с сиротой.
    assert _all_ids(cleaned, "tool_use", "id") == ["A7e", "AuT"]
    assert cleaned[-1]["content"] == [_text("ответ 3")]


def test_window_that_is_one_long_tool_loop_keeps_consistent_tail():
    # Вырожденный случай: во всём окне нет ни одного текстового user-сообщения.
    messages = [
        {"role": "user", "content": [_tool_result("X0")]},
        {"role": "assistant", "content": [_thinking(), _tool_use("X1")]},
        {"role": "user", "content": [_tool_result("X1")]},
        {"role": "assistant", "content": [_tool_use("X2")]},
        {"role": "user", "content": [_tool_result("X2")]},
        {"role": "assistant", "content": [_text("готово")]},
    ]
    cleaned = _validate_history(messages)
    # Начать с user-текста тут нельзя; главное — не отдать API сироту.
    if cleaned:
        _assert_api_valid(cleaned)


def test_valid_history_is_unchanged():
    messages = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": [_thinking(), _tool_use("A")]},
        {"role": "user", "content": [_tool_result("A")]},
        {"role": "assistant", "content": [_text("ок")]},
    ]
    assert _validate_history(messages) == messages


def test_mid_window_orphan_still_stripped():
    messages = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": [_text("сек"), _tool_use("LOST")]},  # результат не сохранился
        {"role": "user", "content": "ну?"},
        {"role": "assistant", "content": [_text("ок")]},
    ]
    cleaned = _validate_history(messages)
    _assert_api_valid(cleaned)
    assert _all_ids(cleaned, "tool_use", "id") == []
