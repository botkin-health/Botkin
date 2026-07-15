from core.personas import PERSONAS, DEFAULT_PERSONA, get_persona, Persona


def test_registry_has_four_personas_with_unique_keys():
    assert set(PERSONAS) == {"caring_doctor", "strict_coach", "meticulous_professor", "calm_mentor"}
    assert len(PERSONAS) == 4


def test_each_persona_has_nonempty_fields():
    for key, p in PERSONAS.items():
        assert isinstance(p, Persona)
        assert p.key == key
        assert p.display.strip()
        assert p.tagline.strip()
        assert p.tone_prompt.strip()


def test_default_persona_is_caring_doctor():
    assert DEFAULT_PERSONA == "caring_doctor"
    assert DEFAULT_PERSONA in PERSONAS


def test_get_persona_falls_back_to_default_on_unknown_or_none():
    assert get_persona(None).key == DEFAULT_PERSONA
    assert get_persona("bogus").key == DEFAULT_PERSONA
    assert get_persona("strict_coach").key == "strict_coach"
