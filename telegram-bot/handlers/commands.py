#!/usr/bin/env python3
"""
Обработчик команд бота (/start, /help, /day, /week, /vitamins и т.д.)
"""

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from datetime import datetime

from core.storage import get_today_totals
from core.garmin_data import get_garmin_data_for_date, get_average_stats
from core.weekly_nutrition import analyze_weekly_nutrition
from core.nutrition_targets import calculate_targets, check_feasibility
from core.supplements import supplement_service

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я HealthVault Tracker - бот для учёта питания и здоровья.\n\n"
        "📸 Отправь фото еды/таблеток с описанием.\n"
        "🗣 Или просто скажи голосом: 'Выпил витамины', 'Съел яблоко'.\n\n"
        "Команды:\n"
        "/day - итоги дня (еда + витамины)\n"
        "/vitamins - чек-лист добавок\n"
        "/week - анализ недели\n"
        "/help - справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 <b>Справка по боту:</b>\n\n"
        "🍽 <b>Еда:</b>\n"
        "📸 <b>Фото:</b> Фото тарелки. Бот поймет состав и вес.\n"
        "🗣 <b>Голос:</b> 'Завтрак: 2 яйца и хлеб'.\n"
        "📝 <b>Текст:</b> 'Ужин: стейк и салат'.\n"
        "<i>💡 Называйте прием (Завтрак/Ужин) или учту текущее время. Это для контроля углеводов.</i>\n\n"
        "💊 <b>Витамины и Лекарства:</b>\n"
        "📸 <b>Фото:</b> Таблетки на ладони или упаковки.\n"
        "🗣 <b>Голос:</b> 'Выпил утренние', 'Принял нурофен'.\n"
        "📝 <b>Текст:</b> 'Омега и Д3 плюс'.\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/day — Итоги дня: КБЖУ, спорт, витамины.\n"
        "/vitamins — Чек-лист и схема приема.\n"
        "/week — Анализ рациона за неделю.\n"
        "/help — Эта справка."
    )


@router.message(Command("day"))
async def cmd_day(message: Message):
    """Обработчик команды /day (бывший /status) - итоги дня"""
    import logging
    import asyncio
    from core.garmin_data import sync_garmin_data, get_average_stats
    
    logger = logging.getLogger(__name__)
    logger.info(f"📊 Команда /day вызвана пользователем {message.from_user.id}")
    
    status_msg = await message.answer("🔄 Синхронизирую данные Garmin...")
    
    try:
        # Update Garmin Data (in thread to not block event loop)
        await asyncio.to_thread(sync_garmin_data)
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_formatted = datetime.now().strftime('%d.%m.%Y')
        
        totals = get_today_totals()
        
        # Garmin Data (Actual for TODAY)
        garmin_data = get_garmin_data_for_date(today)
        active_calories = 0.0
        if garmin_data:
            active_calories = garmin_data.get('activeKilocalories', 0.0) or 0.0
        
        # Targets Calculation (Based on Average History)
        # Получаем средние статы за 14 дней для расчета планки
        avg_stats = get_average_stats(days=14) 
        targets_data = calculate_targets(stats=avg_stats) # Передаем словарь stats
        
        targets = {
            'calories': targets_data['calories'],
            'protein': targets_data['protein'],
            'fats': targets_data['fats'],
            'carbs': targets_data['carbs'],
        }
        
        # Remaining
        remaining = {
            'calories': targets['calories'] - totals['calories'],
            'protein': targets['protein'] - totals['protein'],
        }
        
        # Supplements Status
        supplements_text = supplement_service.get_brief_status()
        
        # Response Construction
        response_parts = [
            f"📅 <b>Итоги дня {today_formatted}</b>",
            "",
            "🥦 <b>Питание:</b>",
            f"• Калории: <b>{totals['calories']:.0f}</b> / {targets['calories']} ккал (Дефицит 15%)",
            f"• Белки: <b>{totals['protein']:.0f}</b> / {targets['protein']} г",
            f"• Жиры: {totals['fats']:.0f} / {targets['fats']} г",
            f"• Углеводы: {totals['carbs']:.0f} / {targets['carbs']} г",
            "",
            f"🔥 Активность (сегодня): <b>{active_calories:.0f}</b> ккал",
            "",
            supplements_text
        ]
        
        # Feasibility Warning
        feasibility_warning = check_feasibility(remaining['calories'], remaining['protein'])
        if feasibility_warning:
             response_parts.append(f"\n⚠️ <i>{feasibility_warning}</i>")

        # Delete waiting message and send result
        await status_msg.delete()
        await message.answer("\n".join(response_parts))
        
    except Exception as e:
        logger.error(f"Error in /day: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка при получении статистики: {e}")


@router.message(Command("vitamins"))
async def cmd_vitamins(message: Message):
    """Обработчик команды /vitamins - статус приема добавок"""
    try:
        status = supplement_service.get_detailed_schedule()
        await message.answer(status)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("week"))
async def cmd_week(message: Message):
    """Обработчик команды /week - анализ недели"""
    try:
        # Получаем данные
        weekly_data = analyze_weekly_nutrition(last_7_days=True)
        totals = weekly_data.get('totals', {})
        days_count = weekly_data.get('days_with_data', 0)
        
        if days_count == 0:
            await message.answer("📊 Нет данных за последние 7 дней.")
            return

        # Средние значения
        avg_cal = totals.get('calories', 0) / days_count
        avg_prot = totals.get('protein', 0) / days_count
        avg_fats = totals.get('fats', 0) / days_count
        avg_carbs = totals.get('carbs', 0) / days_count
        avg_fiber = totals.get('fiber', 0) / days_count
        
        recommendations = weekly_data.get('recommendations', [])
        
        # Targets for comparison (based on 14-day average or just standard)
        # We need average calories to calculate targets
        # Or we can just use the same avg_cals we calculated for the report effectively?
        # Actually verify logic: calculate_targets needs BMR or Avg.
        # Let's use the avg_cal from the week report itself as the "maintenance estimate" basis?
        # Or better: use the same standard get_average_calories(14) to be consistent with daily.
        base_avg_stats = get_average_stats(days=14) 
        targets_data = calculate_targets(stats=base_avg_stats)
        target_cal = targets_data['calories']
        target_prot = targets_data['protein']
        
        response = [
            f"📊 <b>Анализ за 7 дней</b> (дней с данными: {days_count})",
            "",
            "<b>Средние показатели:</b>",
            f"• Калории: {avg_cal:.0f} ккал (Цель: ~{target_cal} с дефицитом)",
            f"• Белки: {avg_prot:.0f} г (Цель: >{target_prot}г)",
            f"• Жиры: {avg_fats:.0f} г",
            f"• Углеводы: {avg_carbs:.0f} г",
            f"• Клетчатка: {avg_fiber:.0f} г (Норма: >30г)",
            "",
            "<b>🔍 Анализ питания:</b>"
        ]
        
        if recommendations:
            for rec in recommendations:
                response.append(f"• {rec}")
        else:
            response.append("• Ваш рацион выглядит сбалансированным! Продолжайте в том же духе.")
            
        await message.answer("\n".join(response))
        
    except Exception as e:
        await message.answer(f"❌ Ошибка анализа недели: {e}")


# Alias for old users / comfort
@router.message(Command("status"))
async def cmd_status_alias(message: Message):
    await cmd_day(message)


@router.message(Command("burn"))
async def cmd_burn(message: Message):
    """Обработчик команды /burn <калории>"""
    await message.answer("⚠️ Функция ввода активных калорий пока не реализована")


@router.message(Command("targets"))
async def cmd_targets(message: Message):
    """Обработчик команды /targets"""
    await message.answer("⚠️ Настройка целей пока не реализована")


