"""Persona generator — LLM-вызов для трёх персональных блоков промпта."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.onboard.persona_generator import (
    PersonaInput,
    PersonaBlocks,
    generate_persona,
    render_prompt,
)


@pytest.fixture
def sample_input():
    return PersonaInput(
        name="Имя",
        full_name="Фамилия Имя Отчество",
        age="21 год",
        birth_date="2004-08-15",
        location="Москва",
        cohort="family",
        cohort_relationship="член семьи",
        pack_name="respiratory_allergic",
        bio_line="Студент. Аллергия на пыль, поллиноз. Регулярный скрининг КЭ-вакцины.",
        kb_json={
            "blood_tests": [
                {"date": "2025-05-08", "values": {"vitamin_d": 35.4}},
            ],
            "diagnoses": ["J45 Asthma intermittens"],
        },
        profile_md="Профиль Игоря: астма с детства, поллиноз, ежегодная вакцина КЭ.",
        style="ty",
    )


def test_render_prompt_substitutes_all_placeholders(sample_input, tmp_path):
    """После подстановки в шаблоне не остаётся '$' плейсхолдеров."""
    template_path = Path("scripts/server/agent_prompts/templates/family_active_coach.md")
    blocks = PersonaBlocks(
        framing="<framing>",
        chronic="<chronic>",
        open_questions="<open_questions>",
        therapy="<therapy>",
        focus_areas="<focus_areas>",
        typical_questions="<typical_questions>",
    )
    rendered = render_prompt(sample_input, blocks, template_path=template_path)
    # Никаких неподставленных $placeholder
    import re

    leftovers = re.findall(r"\$[a-z_]+", rendered)
    assert not leftovers, f"Unsubstituted placeholders: {leftovers}"
    # Имя подставлено
    assert "Игорь" in rendered
    # Pack описание есть
    assert "respiratory_allergic" in rendered


def test_generate_persona_calls_anthropic(sample_input, monkeypatch):
    """LLM-вызов идёт через anthropic API с правильной моделью."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "framing": "21-летний с астмой...",
                        "chronic": "- J45 Asthma intermittens",
                        "open_questions": "- Витамин D 35 — на нижней границе",
                        "therapy": "Беродуал по требованию",
                        "focus_areas": "Витамин D, аллерго-панель, КЭ",
                        "typical_questions": "Про кошек: реакция на эпителий...",
                    }
                ),
            }
        ]
    }
    with patch("scripts.onboard.persona_generator.requests.post", return_value=fake_response) as mock_post:
        blocks = generate_persona(sample_input)
    assert mock_post.called
    args, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["model"] == "claude-sonnet-4-6"
    assert blocks.framing.startswith("21-летний")
    assert "J45" in blocks.chronic


def test_generate_persona_fallback_on_overload(sample_input, monkeypatch):
    """529 на 4.6 → retry на 4.5."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    overload = MagicMock(status_code=529, text="overloaded")
    success = MagicMock(status_code=200)
    success.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "framing": "x",
                        "chronic": "x",
                        "open_questions": "x",
                        "therapy": "x",
                        "focus_areas": "x",
                        "typical_questions": "x",
                    }
                ),
            }
        ]
    }
    responses = [overload, overload, success]  # 529, 529 (quick retry), 200 on fallback

    with patch("scripts.onboard.persona_generator.requests.post", side_effect=responses) as mock_post:
        with patch("scripts.onboard.persona_generator.time.sleep"):  # speed up
            blocks = generate_persona(sample_input)
    # Третий вызов — на fallback модели
    last_payload = mock_post.call_args_list[-1].kwargs["json"]
    assert last_payload["model"] == "claude-sonnet-4-5"
    assert blocks.framing == "x"


def test_generate_persona_invalid_json_raises(sample_input, monkeypatch):
    """Если Claude вернул мусор вместо JSON — RuntimeError с raw text в сообщении."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"content": [{"type": "text", "text": "this is not json at all"}]}
    with patch("scripts.onboard.persona_generator.requests.post", return_value=fake_response):
        with pytest.raises(RuntimeError) as exc:
            generate_persona(sample_input)
    assert "JSON" in str(exc.value) or "json" in str(exc.value)
    # Должен включать raw text для дебага
    assert "not json" in str(exc.value)


def test_generate_persona_missing_keys_raises(sample_input, monkeypatch):
    """Если в JSON нет каких-то required полей — RuntimeError со списком отсутствующих."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "content": [{"type": "text", "text": json.dumps({"framing": "x"})}]  # 5 keys missing
    }
    with patch("scripts.onboard.persona_generator.requests.post", return_value=fake_response):
        with pytest.raises(RuntimeError) as exc:
            generate_persona(sample_input)
    assert "missing" in str(exc.value).lower()
    # Должен перечислить отсутствующие ключи
    assert "chronic" in str(exc.value)
