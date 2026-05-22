"""Welcome sender — Telegram Bot API + ty/vy style branching."""

from unittest.mock import patch, MagicMock

import pytest

from scripts.onboard.welcome_sender import build_welcome_text, send_welcome


def test_build_welcome_text_ty_style():
    text = build_welcome_text(name="Игорь", style="ty", inviter_name="Александр")
    assert "Игорь" in text
    # На «ты» — должно быть «тебе» / «твоя»
    assert "тебе" in text.lower() or "твою" in text.lower() or "твои" in text.lower()
    assert "Александр" in text or "пап" in text.lower()
    # Должна быть подсказка как начать
    assert "витамин" in text.lower() or "анализ" in text.lower()


def test_build_welcome_text_vy_style():
    text = build_welcome_text(name="Валерия", style="vy", inviter_name="Александр")
    # На «Вы» — должно быть «Вам» / «Ваши»
    assert "Вам" in text or "Вашу" in text or "Ваши" in text


def test_send_welcome_calls_telegram_api(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    with patch("scripts.onboard.welcome_sender.requests.post", return_value=fake_response) as mock_post:
        msg_id = send_welcome(chat_id=999, text="hello")
    assert msg_id == 42
    args, kwargs = mock_post.call_args
    assert "test-token" in args[0]
    assert kwargs["json"]["chat_id"] == 999
    assert kwargs["json"]["text"] == "hello"


def test_send_welcome_raises_on_api_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    fake_response = MagicMock(status_code=400)
    fake_response.json.return_value = {"ok": False, "description": "chat not found"}

    with patch("scripts.onboard.welcome_sender.requests.post", return_value=fake_response):
        with pytest.raises(RuntimeError) as exc:
            send_welcome(chat_id=999, text="hello")
    assert "chat not found" in str(exc.value)
