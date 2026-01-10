#!/usr/bin/env python3
"""
Обработчик команд бота (/start, /help, /status и т.д.)
"""

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from datetime import datetime

from services.storage import get_today_totals
from services.garmin_data import get_garmin_data_for_date, get_average_calories
from services.weekly_nutrition import analyze_weekly_nutrition
from services.nutrition_targets import calculate_targets, check_feasibility

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я HealthVault Tracker - бот для учёта питания.\n\n"
        "📸 Отправь фото еды с описанием, и я рассчитаю КБЖУ.\n\n"
        "Команды:\n"
        "/help - справка\n"
        "/status - сколько осталось сегодня"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Справка по использованию бота:\n\n"
        "1. 📸 Отправь фото еды (можно несколько фото)\n"
        "2. 📝 Напиши описание блюда:\n"
        "   • Название блюда\n"
        "   • Компоненты с весами (например: 'курица 200г, рис 150г')\n"
        "   • Или просто список продуктов - веса распознаются с фото автоматически\n\n"
        "Примеры:\n"
        "• 'гречка 250г, лосось 120г, авокадо 80г'\n"
        "• 'куриное филе, фасоль, капуста (вес на фото)'\n"
        "• 'салат: помидоры 150г, огурцы 100г, масло 1 ч.л.'\n\n"
        "Команды:\n"
        "/start - начать работу\n"
        "/status - сколько осталось сегодня\n"
        "/help - эта справка"
    )


def generate_recommendations(totals: dict, targets: dict) -> str:
    """Генерирует рекомендации по продуктам на основе недостающих макронутриентов"""
    recommendations = []
    
    # Проверяем белки
    protein_remaining = targets['protein'] - totals['protein']
    if protein_remaining > 20:
        recommendations.append("яйца")
        recommendations.append("орехи")
    
    # Проверяем жиры
    fats_remaining = targets['fats'] - totals['fats']
    if fats_remaining > 10:
        recommendations.append("орехи")
        recommendations.append("авокадо")
    
    # Проверяем углеводы
    carbs_remaining = targets['carbs'] - totals['carbs']
    if carbs_remaining > 30:
        recommendations.append("крестоцветные овощи")
        recommendations.append("гречка")
    
    # Если мало всего
    if protein_remaining > 30 and fats_remaining > 15:
        recommendations = ["яйца", "орехи", "крестоцветные овощи"]
    
    if not recommendations:
        return "баланс в норме"
    
    # Убираем дубликаты и возвращаем
    unique_recs = []
    for rec in recommendations:
        if rec not in unique_recs:
            unique_recs.append(rec)
    
    return ", ".join(unique_recs)


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Обработчик команды /status - показывает остаток КБЖУ на сегодня"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"📊 Команда /status вызвана пользователем {message.from_user.id}")
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        today_formatted = datetime.now().strftime('%d.%m.%Y')
        
        totals = get_today_totals()
        
        # Получаем данные Garmin
        garmin_data = get_garmin_data_for_date(today)
        active_calories = 0.0
        if garmin_data:
            active_calories = garmin_data.get('activeKilocalories', 0.0) or 0.0
        
        # Получаем средний расход калорий (теперь за 14 дней с фильтрацией)
        avg_calories = get_average_calories(days=14)
        
        # Рассчитываем динамические цели
        targets_data = calculate_targets(avg_calories)
        target_calories = targets_data['calories']
        
        targets = {
            'calories': target_calories,
            'protein': targets_data['protein'],
            'fats': targets_data['fats'],
            'carbs': targets_data['carbs'],
        }
        
        # Рассчитываем дефицит
        deficit = 0
        if avg_calories > 0:
            deficit = round(avg_calories - target_calories, 0)
        
        # Рассчитываем остаток
        remaining = {
            'calories': targets['calories'] - totals['calories'],
            'protein': targets['protein'] - totals['protein'],
            'fats': targets['fats'] - totals['fats'],
            'carbs': targets['carbs'] - totals['carbs'],
        }
        
        # Генерируем рекомендации
        recommendations = generate_recommendations(totals, targets)
        
        # Получаем недельный анализ
        weekly_data = analyze_weekly_nutrition(last_7_days=True)
        weekly_totals = weekly_data.get('totals', {})
        weekly_recommendations = weekly_data.get('recommendations', [])
        
        # Формируем ответ в формате как на скриншоте
        response_parts = [
            f"■ Статус на {today_formatted}",
            "",
            "🎯 Цели:",
            f"• Калории: {targets['calories']} ккал"
        ]
        
        if avg_calories > 0:
            response_parts.append(f"  (среднее: ~{avg_calories:.0f} ккал, дефицит: ~{deficit:.0f} ккал)")
        
        response_parts.append(f"• Белки: {targets['protein']} г")
        response_parts.extend([
            "",
            "✅ Уже съедено:",
            f"• Калории: {totals['calories']:.0f} ккал",
            f"• Белки: {totals['protein']:.0f} г",
            f"• Жиры: {totals['fats']:.0f} г",
            f"• Углеводы: {totals['carbs']:.0f} г",
            "",
            f"🔥 Активные калории: {active_calories:.0f} ккал",
            "",
            "📈 Осталось:",
        ])
        
        # Проверка достижимости белка
        feasibility_warning = check_feasibility(
            remaining['calories'], 
            remaining['protein']
        )
        
        response_parts.append(f"• Калории: {remaining['calories']:.0f} ккал")
        if feasibility_warning:
            response_parts.append(f"• Белки: {remaining['protein']:.0f} г ⚠️")
        else:
            response_parts.append(f"• Белки: {remaining['protein']:.0f} г")
            
        if feasibility_warning:
            response_parts.append("")
            response_parts.append(feasibility_warning)
        
        # Добавляем недельную статистику
        if weekly_totals:
            days_count = weekly_data.get('days_with_data', 7)
            if days_count == 0:
                days_count = 1  # Avoid division by zero
                
            week_calories = weekly_totals.get('calories', 0) / days_count
            week_protein = weekly_totals.get('protein', 0) / days_count
            week_fiber = weekly_totals.get('fiber', 0) / days_count
            
            response_parts.extend([
                "",
                f"📊 Последние 7 дней (среднее/день, данные за {days_count} дн.):",
                f"• Калории: {week_calories:.0f} ккал",
                f"• Белки: {week_protein:.0f} г",
                f"• Клетчатка: {week_fiber:.0f} г",
            ])
        
        # Добавляем рекомендации (сначала ежедневные, потом недельные)
        response_parts.extend([
            "",
            "💡 Рекомендации:",
        ])
        
        if recommendations and recommendations != "баланс в норме":
            response_parts.append(recommendations)
        
        # Добавляем недельные рекомендации
        if weekly_recommendations:
            if recommendations and recommendations != "баланс в норме":
                response_parts.append("")
            for rec in weekly_recommendations:
                response_parts.append(rec)
        
        response = "\n".join(response_parts)
        
        await message.answer(response)
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении статистики: {e}")


@router.message(Command("burn"))
async def cmd_burn(message: Message):
    """Обработчик команды /burn <калории> - ввод активных калорий"""
    # TODO: Реализовать ввод активных калорий
    await message.answer("⚠️ Функция ввода активных калорий пока не реализована")


@router.message(Command("targets"))
async def cmd_targets(message: Message):
    """Обработчик команды /targets - настройка целей"""
    # TODO: Реализовать настройку целей
    await message.answer("⚠️ Настройка целей пока не реализована")

