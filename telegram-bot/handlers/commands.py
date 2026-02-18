#!/usr/bin/env python3
"""
Обработчик команд бота (/start, /help, /day, /week, /vitamins и т.д.)
"""

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from datetime import datetime

from core.garmin_data import get_garmin_data_for_date, get_average_stats
from core.weekly_nutrition import analyze_weekly_nutrition
from core.nutrition_targets import calculate_targets, check_feasibility
# NOTE: SupplementService imported per-request to support multi-user

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, user_id: int, username: str, first_name: str):
    """Обработчик команды /start - регистрация и приветствие"""
    # Register user in database
    from database import SessionLocal
    from database.crud import ensure_user_exists
    
    db = SessionLocal()
    try:
        user = ensure_user_exists(
            db, 
            telegram_id=user_id,
            username=username,
            first_name=first_name
        )
        db.close()
    except Exception as e:
        db.close()
        await message.answer(f"❌ Error registering user: {e}")
        return
    
    await message.answer(
        f"👋 Привет, {first_name}! Я HealthVault Tracker - бот для учёта питания и здоровья.\n\n"
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
    """Справка по командам"""
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
        "/cache_stats — Статистика кэша (экономия токенов).\n"
        "/help — Эта справка."
    )


@router.message(Command("day"))
async def cmd_day(message: Message, user_id: int):
    """Показывает итоги дня"""
    import logging
    import asyncio
    from core.garmin_data import sync_garmin_data, get_average_stats
    
    logger = logging.getLogger(__name__)
    logger.info(f"📊 Команда /day вызвана пользователем {message.from_user.id}")
    
    status_msg = await message.answer("🔄 Синхронизирую данные Garmin...")
    
    db = None
    try:
        from database import SessionLocal
        db = SessionLocal()

        # Умная синхронизация - только недостающие дни
        from core.garmin_data import sync_missing_garmin_days
        missing_count = sync_missing_garmin_days(user_id=user_id)
        
        today_date = datetime.now().date()
        today_str = today_date.strftime('%Y-%m-%d')
        today_formatted = today_date.strftime('%d.%m.%Y')
        
        # New Service Logic
        from services.nutrition_service import get_nutrition_service
        service = get_nutrition_service(user_id=user_id)
        stats = service.get_day_stats(today_date)
        
        totals = stats['totals']
        targets = stats['targets']
        remaining = stats['remaining']
        
        # Garmin Data (Actual for TODAY)
        garmin_data = get_garmin_data_for_date(today_str, user_id=user_id)
        active_calories = 0.0
        if garmin_data:
            active_calories = garmin_data.get('activeKilocalories', 0.0) or 0.0
        
        # Supplements Status - create per-user instance
        from core.supplements import SupplementService
        user_supplement_service = SupplementService(user_id=user_id)
        supplements_text = user_supplement_service.get_brief_status()
        
        # Apple Health - latest weight
        from database.crud import get_latest_weight
        weight_text = ""
        weight = get_latest_weight(db, user_id)
        if weight:
            # Only show if recorded today
            if weight.measured_at.date() == today_date:
                weight_text = f"⚖️ Вес: <b>{weight.weight} кг</b>"
        
        # Response Construction
        response_parts = [
            f"📅 <b>Итоги дня {today_formatted}</b>",
            "",
            "🥦 <b>Питание:</b>",
            f"• Калории: <b>{totals.calories:.0f}</b> / {targets['calories']} ккал (Дефицит 15%)",
            f"• Белки: <b>{totals.protein:.0f}</b> / {targets['protein']} г",
            f"• Жиры: {totals.fats:.0f} / {targets['fats']} г",
            f"• Углеводы: {totals.carbs:.0f} / {targets['carbs']} г",
            "",
            f"🔥 Активность (сегодня): <b>{active_calories:.0f}</b> ккал",
            "",
            supplements_text
        ]
        
        # Add weight if available
        if weight_text:
            response_parts.insert(-1, weight_text)
            response_parts.insert(-1, "")
        
        # Feasibility Warning
        feasibility_warning = check_feasibility(remaining['calories'], remaining['protein'])
        if feasibility_warning:
             response_parts.append(f"\n⚠️ <i>{feasibility_warning}</i>")

        # Delete waiting message and send result
        await status_msg.delete()
        await message.answer("\n".join(response_parts))
        
    except Exception as e:
        logger.error(f"Error in /day: {e}", exc_info=True)
        import html
        await status_msg.edit_text(f"❌ Ошибка при получении статистики: {html.escape(str(e))}")
    finally:
        if db:
            db.close()


@router.message(Command("vitamins"))
async def cmd_vitamins(message: Message, user_id: int):
    """Чек-лист приема витаминов и добавок"""
    try:
        # Create per-user supplement service
        from core.supplements import SupplementService
        user_supplement_service = SupplementService(user_id=user_id)
        status = user_supplement_service.get_detailed_schedule()
        await message.answer(status)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("week"))
async def cmd_week(message: Message, user_id: int):
    """Анализ недели"""
    try:
        # Получаем данные
        weekly_data = analyze_weekly_nutrition(user_id=user_id)
        totals = weekly_data.get('totals', {})
        days_count = weekly_data.get('days_with_data', 0)
        
        if days_count == 0:
            await message.answer("📊 Нет данных за последние 7 дней.")
            return

        # Средние значения потребления
        avg_consumed = totals.get('calories', 0) / days_count
        avg_prot = totals.get('protein', 0) / days_count
        avg_fats = totals.get('fats', 0) / days_count
        avg_carbs = totals.get('carbs', 0) / days_count
        avg_fiber = totals.get('fiber', 0) / days_count
        
        # TDEE (расход) и дефицит
        avg_tdee = totals.get('avg_tdee', 0)
        avg_active_cal = totals.get('avg_active_cal', 0)
        avg_bmr = totals.get('avg_bmr', 1700)
        
        # Расчет дефицита
        deficit = avg_tdee - avg_consumed
        deficit_pct = (deficit / avg_tdee * 100) if avg_tdee > 0 else 0
        
        # Цель с дефицитом 15%
        target_cal = avg_tdee * 0.85
        
        # Эмодзи для оценки дефицита
        if deficit_pct < 10:
            deficit_emoji = "⚠️"  # Слишком мало
        elif 10 <= deficit_pct <= 20:
            deficit_emoji = "✅"  # Отлично
        elif 20 < deficit_pct <= 30:
            deficit_emoji = "👍"  # Хорошо
        else:
            deficit_emoji = "⚠️"  # Слишком много
        
        # Целевые значения БЖУ
        target_protein = 150  # Целевое значение
        
        recommendations = weekly_data.get('recommendations', [])
        
        # Заголовок (показываем дни только если не все 7)
        if days_count < 7:
            title = f"📊 Анализ за 7 дней (дней с данными: {days_count})"
        else:
            title = "📊 Анализ за 7 дней"
        
        response = [
            title,
            "",
            "📥 Среднее потребление:",
            f"• Калории: {avg_consumed:.0f} ккал",
            f"• Белки: {avg_prot:.0f} г (Цель: > {target_protein}г)",
            f"• Жиры: {avg_fats:.0f} г",
            f"• Углеводы: {avg_carbs:.0f} г",
            f"• Клетчатка: {avg_fiber:.0f} г (Норма: > 30г)",
            "",
            f"🔥 Расход {avg_tdee:.0f} = {avg_bmr:.0f}😴 + {avg_active_cal:.0f}🏃",
            f"🎯 Цель {target_cal:.0f} (-15%) : {deficit:.0f} ({deficit_pct:.1f}%) {deficit_emoji}",
            "",
            "🔍 Анализ питания:"
        ]
        
        if recommendations:
            for rec in recommendations:
                response.append(f"• {rec}")
        else:
            response.append("• Ваш рацион выглядит сбалансированным! Продолжайте в том же духе.")
            
        await message.answer("\n".join(response))
        
    except Exception as e:
        await message.answer(f"❌ Ошибка анализа недели: {e}")


@router.message(Command("cache_stats"))
async def cmd_cache_stats(message: Message):
    """Показывает статистику Image Cache"""
    try:
        from infrastructure.cache.image_cache import get_image_cache
        cache = get_image_cache()
        stats = cache.stats()
        
        total = stats['total']
        valid = stats['valid']
        expired = stats['expired']
        
        if total == 0:
            await message.answer(
                "📊 <b>Статистика кэша изображений</b>\n\n"
                "Кэш пустой. Отправьте фото для создания первой записи."
            )
        else:
            hit_rate = (valid / total * 100) if total > 0 else 0
            await message.answer(
                "📊 <b>Статистика кэша изображений</b>\n\n"
                f"• Всего записей: {total}\n"
                f"• Активных: {valid}\n"
                f"• Просрочено: {expired}\n"
                f"• Hit Rate: ~{hit_rate:.0f}%\n\n"
                f"💰 Экономия: ~${valid * 0.01:.2f}\n"
                f"📅 TTL: 7 дней"
            )
    except ImportError:
        await message.answer("❌ Кэш не настроен")


@router.message(Command("cache_clear"))
async def cmd_cache_clear(message: Message):
    """Очищает Image Cache"""
    try:
        from infrastructure.cache.image_cache import get_image_cache
        cache = get_image_cache()
        
        stats_before = cache.stats()
        cache.clear()
        
        await message.answer(
            "🗑 <b>Кэш очищен</b>\n\n"
            f"Удалено записей: {stats_before['total']}\n"
            f"Освобождено места: ~{stats_before['total'] * 10}KB"
        )
    except ImportError:
        await message.answer("❌ Кэш не настроен")


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



