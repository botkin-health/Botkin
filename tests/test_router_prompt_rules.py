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


# Issue #446: роутер иногда переносит вес одного ингредиента на другой,
# когда в одном сообщении указаны РАЗНЫЕ явные веса для нескольких позиций
# (напр. "гречка 150 г и куриная грудка 120 г" → оба ушли как 150г).
#
# Это стохастика LLM (см. оговорку в issue), не детерминированный баг кода —
# промпт и до этой правки логически требовал независимый вес на каждый
# ингредиент. Задача теста — только застраховать сам факт наличия точечного
# правила и примера в SYSTEM_PROMPT от случайной потери при будущих правках
# промпта, а не гарантировать поведение модели на живом API. Живой
# LLM-регресс-тест на конкретную фразу не добавляем: он не даёт вероятностной
# гарантии и не должен быть частью блокирующего сьюта (best effort, см. план
# в issue).
def test_system_prompt_contains_multiple_items_independent_weights_rule():
    assert "MULTIPLE ITEMS WITH DIFFERENT EXPLICIT WEIGHTS IN ONE MESSAGE" in SYSTEM_PROMPT
    assert "each item's weight is INDEPENDENT" in SYSTEM_PROMPT
    assert "гречка 150 г и куриная грудка 120 г" in SYSTEM_PROMPT
    assert "NOT both 150" in SYSTEM_PROMPT
