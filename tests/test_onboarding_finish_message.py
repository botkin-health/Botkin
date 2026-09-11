"""#436: финальное сообщение онбординга должно явно объяснять двухшаговый
флоу логирования еды — иначе пользователь думает, что отправка фото/текста
уже сохранила запись, и молча теряет данные (прецедент: 30 фото еды за
3 недели, 0 сохранений в nutrition_log — ни разу не нажата кнопка
«Сохранить» ни «Отмена»).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
async def test_finish_onboarding_explains_confirm_step(mock_send):
    """Финальное сообщение должно упоминать карточку с КБЖУ и кнопку «Сохранить»."""
    from handlers.onboarding import _finish_onboarding

    db = MagicMock()
    user = MagicMock(
        telegram_id=999888,
        onboarding_data={"persona": None},
        health_token=None,
        share_token=None,
    )

    await _finish_onboarding(user, db, chat_id=999888)

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    sent_text = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("text")

    assert "Сохранить" in sent_text
    assert "карточк" in sent_text.lower() or "распознан" in sent_text.lower()


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
async def test_finish_onboarding_keeps_call_to_action(mock_send):
    """Не должны потерять исходный призыв «напиши или сфоткай, что ел» при правке."""
    from handlers.onboarding import _finish_onboarding

    db = MagicMock()
    user = MagicMock(
        telegram_id=999889,
        onboarding_data={"persona": None},
        health_token=None,
        share_token=None,
    )

    await _finish_onboarding(user, db, chat_id=999889)

    sent_text = mock_send.call_args[0][1]
    assert "сфоткай" in sent_text.lower()


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
async def test_finish_onboarding_does_not_require_doc_command(mock_send):
    """#439/#441/#449: анализы теперь распознаются автоматически без /doc —

    финальное сообщение не должно учить новичка команде, которая больше не
    нужна (прецедент этой сессии: подруге Ники объясняли устаревшую /doc,
    хотя бот уже сам предлагает сохранить присланный файл)."""
    from handlers.onboarding import _finish_onboarding

    db = MagicMock()
    user = MagicMock(
        telegram_id=999890,
        onboarding_data={"persona": None},
        health_token=None,
        share_token=None,
    )

    await _finish_onboarding(user, db, chat_id=999890)

    sent_text = mock_send.call_args[0][1]
    assert "/doc" not in sent_text
    assert "анализ" in sent_text.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
