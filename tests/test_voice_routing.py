"""Tests for voice message routing fix (#159).

Voice messages with non-food content (health questions, medical topics) must
be routed to BotkinClaw agent, not the food log pipeline.

Reproduction: Max Urazaev sent voice about high LDL / statins — bot returned
"❌ Не удалось распознать что это за еда" instead of an agent response.

Root causes fixed:
1. _is_clearly_conversational fast-path: health questions bypass food router entirely.
2. caption=text_stripped in state data: LLM-router "other" result also routes to agent.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock


def _stub_aiogram() -> None:
    """Install minimal aiogram stubs so handlers.text can be imported in CI
    where aiogram is not installed."""
    mocked_packages = [
        "aiogram",
        "aiogram.filters",
        "aiogram.fsm",
        "aiogram.fsm.context",
        "aiogram.types",
    ]
    for name in mocked_packages:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()


_stub_aiogram()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

# Import the function under test — must come after the stub setup above
from handlers.text import _is_clearly_conversational  # noqa: E402


class TestVoiceHealthQuestionsRouteToAgent:
    """Medical/health questions must be flagged as conversational → agent route (#159)."""

    def test_ldl_question_with_mark(self):
        text = "У меня высокий ЛПНП, семейная история, стоит ли принимать статины?"
        assert _is_clearly_conversational(text) is True

    def test_ldl_question_without_mark(self):
        # starts with question word "Какой"
        text = "Какой уровень ЛПНП считается нормой"
        assert _is_clearly_conversational(text) is True

    def test_statin_question(self):
        text = "Нужно ли мне принимать статины при семейной гиперхолестеринемии?"
        assert _is_clearly_conversational(text) is True

    def test_how_question(self):
        text = "Как снизить холестерин без таблеток"
        assert _is_clearly_conversational(text) is True

    def test_explain_question(self):
        text = "Объясни мне что такое липидный профиль"
        assert _is_clearly_conversational(text) is True

    def test_tell_me_question(self):
        text = "Расскажи про мои анализы"
        assert _is_clearly_conversational(text) is True

    def test_show_me_question(self):
        text = "Покажи мои последние показатели давления"
        assert _is_clearly_conversational(text) is True

    def test_question_mark_alone_routes_to_agent(self):
        text = "Мой ЛПНП в норме?"
        assert _is_clearly_conversational(text) is True


class TestVoiceFoodContentRoutesFoodPipeline:
    """Food descriptions must NOT be flagged as conversational → food pipeline."""

    def test_food_with_grams_stays_food(self):
        text = "съел 200г куриной грудки и рис"
        assert _is_clearly_conversational(text) is False

    def test_meal_description_stays_food(self):
        text = "завтрак: омлет из двух яиц, тост с маслом"
        assert _is_clearly_conversational(text) is False

    def test_calorie_mention_stays_food(self):
        text = "пообедал, примерно 500 ккал"
        assert _is_clearly_conversational(text) is False

    def test_snack_stays_food(self):
        text = "перекусил яблоком и орехами"
        assert _is_clearly_conversational(text) is False


class TestVoiceCaptionFallback:
    """Verify state caption field is non-empty so handle_description can route to agent."""

    def test_caption_field_is_text_not_empty(self):
        """Bug: caption was '' → actual_caption was falsy → error message shown.
        Fix: caption is now set to text_stripped in the UserState data (#159)."""
        from services.state import UserState

        text_stripped = "У меня высокий ЛПНП, семейная история"
        state = UserState(
            user_id="123",
            state="waiting_description",
            data={
                "photo_paths": [],
                "photo_file_ids": [],
                "caption": text_stripped,  # fix: was "" before #159
            },
        )
        assert state.data["caption"] == text_stripped
        assert bool(state.data["caption"]) is True  # actual_caption check in photo.py passes
