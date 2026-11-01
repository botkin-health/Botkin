"""Разговор о самочувствии: еда в диалоге, «вчерашний», скриншоты здоровья.

Прецедент E2E 01.11.2026: в разговоре после поездки на море «вчера выпил пару
бокалов шампанского» и «у меня есть квашеная капуста» ушли в парсер еды,
«еды вчерашней» записалась на сегодня, скрин Garmin ушёл в документы.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.photo import _looks_like_health_app_screenshot
from handlers.text import _is_food_mention_in_dialog, extract_date_from_text

TZ = ZoneInfo("Asia/Dubai")


def _yesterday() -> str:
    return (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.mark.parametrize(
    "text",
    [
        "И да, вчера я выпил прям на пляже пару бокалов шампанского",
        "у меня есть квашенная капуста",
        "много мяса ел после купания",
    ],
)
def test_food_mention_in_dialog_goes_to_agent(text):
    assert _is_food_mention_in_dialog(text)


@pytest.mark.parametrize(
    "text",
    [
        "запиши кофе с молоком",
        "надо бы внести вчерашний ужин",
        "овсянка 200г",
        "Обед: суп и салат",
    ],
)
def test_explicit_log_stays_with_parser(text):
    assert not _is_food_mention_in_dialog(text)


@pytest.mark.parametrize(
    "text",
    [
        "я не внес еды вчерашней, надо бы внести",
        "И да, вяера я выпил шампанского",
        "вчра ел плов",
        "вчерашний ужин: рыба",
    ],
)
def test_yesterday_variants(text):
    date_str, _ = extract_date_from_text(text, TZ)
    assert date_str == _yesterday()


def test_day_before_yesterday_adjective():
    date_str, clean = extract_date_from_text("позавчерашний ужин", TZ)
    assert date_str == (datetime.now(TZ) - timedelta(days=2)).strftime("%Y-%m-%d")
    assert clean == "ужин"


def test_no_false_yesterday():
    assert extract_date_from_text("ведро воды", TZ)[0] is None


@pytest.mark.parametrize(
    "caption,reply,expected",
    [
        ("что это со мной? проанализируй все что доступно через гармин", "", True),
        ("", "Отклонений: 2. Частота пульса 66 уд/м, ВЧП 36 мс", True),
        ("вот моя страховка", "", False),
        ("", "Полис ДМС, страховая компания", False),
    ],
)
def test_health_app_screenshot_detector(caption, reply, expected):
    assert _looks_like_health_app_screenshot(caption, reply) is expected
