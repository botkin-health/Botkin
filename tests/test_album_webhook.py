"""Альбом (media_group_id) не должен разваливаться на отдельные фото из-за синхронного webhook."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from middlewares.media_group import MediaGroupMiddleware  # noqa: E402
from webhook import telegram_router as tr  # noqa: E402


def _payload(**extra):
    msg = {"message_id": 1, "from": {"id": 1}, "chat": {"id": 1}, "photo": [{}], **extra}
    return {"update_id": 1, "message": msg}


async def _call_route(payload):
    with patch.object(tr, "_verify_webhook_secret"):
        return await tr.telegram_webhook(payload, x_telegram_bot_api_secret_token=None)


@pytest.mark.asyncio
async def test_album_update_returns_before_handler_finishes():
    done = asyncio.Event()

    async def slow_feed(payload):
        await asyncio.sleep(0.3)
        done.set()
        return True

    with (
        patch.object(tr, "_load_user_flags", return_value=(True, True)),
        patch.object(tr, "_feed_legacy_bot", side_effect=slow_feed),
    ):
        res = await _call_route(_payload(media_group_id="g1"))
        assert res["status"] == "ok"
        assert not done.is_set()  # ответили Telegram, не дождавшись хендлера
        await asyncio.gather(*tr._background_tasks)
        assert done.is_set()
    assert not tr._background_tasks


@pytest.mark.asyncio
async def test_plain_update_is_processed_synchronously():
    done = asyncio.Event()

    async def slow_feed(payload):
        await asyncio.sleep(0.05)
        done.set()
        return True

    with (
        patch.object(tr, "_load_user_flags", return_value=(True, True)),
        patch.object(tr, "_feed_legacy_bot", side_effect=slow_feed),
    ):
        await _call_route(_payload())
        assert done.is_set()
    assert not tr._background_tasks


@pytest.mark.asyncio
async def test_background_failure_is_logged_not_raised(caplog):
    async def boom(payload):
        raise RuntimeError("x")

    with (
        patch.object(tr, "_load_user_flags", return_value=(True, True)),
        patch.object(tr, "_feed_legacy_bot", side_effect=boom),
    ):
        res = await _call_route(_payload(media_group_id="g2"))
        assert res["status"] == "ok"
        await asyncio.gather(*tr._background_tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert "Фоновая обработка update упала" in caplog.text


def _photo_msg(mid, group="g"):
    return Message(
        message_id=mid,
        date=datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="t"),
        photo=[PhotoSize(file_id=f"f{mid}", file_unique_id=f"u{mid}", width=1, height=1)],
        media_group_id=group,
    )


@pytest.mark.asyncio
async def test_middleware_collects_concurrent_album_into_one_call():
    mw = MediaGroupMiddleware(latency=0.05)
    handler_calls = []

    async def handler(event, data):
        handler_calls.append((event, data))

    await asyncio.gather(*(mw(handler, _photo_msg(i), {}) for i in (1, 2, 3)))
    assert len(handler_calls) == 1
    event, data = handler_calls[0]
    assert event.message_id == 1
    assert [m.message_id for m in data["album"]] == [1, 2, 3]
    assert MediaGroupMiddleware.ALBUM_DATA == {}


def test_default_latency_gives_network_slack():
    assert MediaGroupMiddleware().latency >= 1.5
