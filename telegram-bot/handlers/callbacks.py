from aiogram.filters.callback_data import CallbackData


# Callback data для кнопок подтверждения
class MealConfirmationCallback(CallbackData, prefix="meal"):
    action: str  # "save" или "cancel"
    meal_type: str = "default"  # "menu" или "regular"


class WeightConfirmationCallback(CallbackData, prefix="weight"):
    action: str  # "save" или "cancel"
