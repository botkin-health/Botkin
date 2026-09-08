"""
Регрессионный guard: правило CASE B + MODIFIER в SYSTEM_PROMPT (SCENARIO 1.1)
не должно случайно затеряться при последующих правках промпта.

Контекст: карточки meal-kit (Elementaree, Шефмаркет, HelloFresh) печатают
"на порцию" итог, но список ингредиентов рассчитан на ВЕСЬ набор (часто
2 порции). Если пользователь пишет "без кускуса"/"минус масло" и т.п.,
модель не должна пересобирать блюдо суммированием ингредиентов набора —
итог с карточки должен оставаться якорем.
"""

from core.llm.router import SYSTEM_PROMPT


def test_system_prompt_contains_case_b_modifier_rule():
    assert "CASE B + MODIFIER" in SYSTEM_PROMPT
    assert "WHOLE KIT" in SYSTEM_PROMPT


def test_case_b_modifier_rule_is_attached_right_after_case_b():
    case_b_index = SYSTEM_PROMPT.index("CASE B:")
    modifier_index = SYSTEM_PROMPT.index("CASE B + MODIFIER")
    scenario_1_2_index = SYSTEM_PROMPT.index("SCENARIO 1.2:")

    assert case_b_index < modifier_index < scenario_1_2_index
