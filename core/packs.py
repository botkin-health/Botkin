"""Pack registry — декларативный список фокусных профилей.

Pack — это тэг направления коучинга в system_prompt + блоки дашборда + шаблон
отчёта. Захардкожен как Python-модуль (а не БД/JSON) потому что dashboard_blocks
и report_template — это код, не data.

Используется:
- scripts/onboard_family_user.py (валидация при --pack X)
- ...будущее: core/reports/* для выбора блоков в отчёте
- ...будущее: dashboard_generator для блоков дашборда

См. design: docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Pack:
    """Фокусный профиль здоровья."""

    name: str
    description: str
    focus_areas: tuple[str, ...]
    dashboard_blocks: tuple[str, ...]
    report_template: Optional[str]  # путь к Jinja2 шаблону отчёта; None если ещё нет


PACKS: dict[str, Pack] = {
    "bariatric": Pack(
        name="bariatric",
        description="Снижение веса + метаболика",
        focus_areas=("weight", "metabolic_panel", "blood_pressure", "macros"),
        dashboard_blocks=("weight_trend", "calorie_balance", "macros"),
        report_template=None,
    ),
    "cardiac": Pack(
        name="cardiac",
        description="Кардиометаболический риск",
        focus_areas=("blood_pressure", "lipids", "ecg", "physical_activity"),
        dashboard_blocks=("bp_trend", "lipids_panel", "activity"),
        report_template=None,
    ),
    "generic": Pack(
        name="generic",
        description="Общий профиль без специфического фокуса",
        focus_areas=("general_screening",),
        dashboard_blocks=("weight_trend", "activity"),
        report_template=None,
    ),
    "respiratory_allergic": Pack(
        name="respiratory_allergic",
        description="Астма + аллерго-история + регулярный скрининг (КЭ-антитела, витD)",
        focus_areas=(
            "asthma_allergy_panel",
            "vitamin_d",
            "pollen_seasonal",
            "tick_antibodies",
        ),
        dashboard_blocks=("vitamin_d_trend", "allergy_history", "tick_antibodies"),
        report_template=None,
    ),
}


def get_pack(name: str) -> Pack:
    """Получить Pack по имени, иначе ValueError со списком доступных."""
    if name not in PACKS:
        raise ValueError(f"Unknown pack: {name!r}. Available: {sorted(PACKS.keys())}")
    return PACKS[name]
