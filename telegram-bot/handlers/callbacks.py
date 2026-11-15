from aiogram.filters.callback_data import CallbackData


# Callback data для кнопок подтверждения
class MealConfirmationCallback(CallbackData, prefix="meal"):
    action: str  # "save", "cancel" или "set_slot" (#181: выбор слота для фото без подписи)
    meal_type: str = "default"  # "menu" или "regular"
    slot: str = ""  # breakfast/lunch/snack/dinner — только для action="set_slot"


class WeightConfirmationCallback(CallbackData, prefix="weight"):
    action: str  # "save" или "cancel"


class HealthConnectCallback(CallbackData, prefix="ahconn"):
    method: str  # "hae" (Health Auto Export) или "shortcut" (бесплатный iOS Shortcut)


class SupplementConfirmationCallback(CallbackData, prefix="suppl"):
    action: str  # "save" или "cancel"


class DayCheckCallback(CallbackData, prefix="daychk"):
    """Кнопки утреннего вопроса «вчера внёс всё?» (адаптивная цель, ADR-0015)."""

    answer: str  # "yes" — день полный | "no" — что-то пропустил
    date: str  # YYYY-MM-DD


class PlanCloseCallback(CallbackData, prefix="plan"):
    """Кнопки вечернего вопроса «план на сегодня доеден целиком?» (#407)."""

    action: str  # "all" — закрыть все планы дня | "edit" — подсказать, как править
    date: str  # YYYY-MM-DD
