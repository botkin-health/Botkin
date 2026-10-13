"""«Арахисовая паста» не должна получать дефолт 250 г от «паста» (макароны).

Прецедент 13.10.2026: 25 г арахисовой пасты → 250 г → ×10 ккал → все позиции обеда
ужаты до заявленного итога (огурцы 24→9 ккал, хумус 54→22).
"""

import pytest

from core.food.description_parser import get_default_unit_weight


@pytest.mark.parametrize(
    "name",
    ["Арахисовая паста", "паста ореховая", "Тахини (кунжутная паста)", "шоколадная паста"],
)
def test_spread_paste_has_no_pasta_default(name):
    assert get_default_unit_weight(name) == 0


@pytest.mark.parametrize("name", ["паста", "Паста карбонара", "паста болоньезе"])
def test_real_pasta_keeps_default(name):
    assert get_default_unit_weight(name) == 250
