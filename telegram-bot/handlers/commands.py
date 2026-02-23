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
        "/day — итоги дня (еда + витамины)\n"
        "/vitamins — чек-лист добавок\n"
        "/week — анализ недели\n"
        "/setup — BMR и калории (без Garmin)\n"
        "/help — справка"
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
        "/setup — Настройка BMR и активных калорий (для тех, кто без Garmin).\n"
        "/activity <число> — Ввести активные калории за сегодня вручную.\n"
        "/help — Эта справка."
    )


@router.message(Command("day"))
async def cmd_day(message: Message, user_id: int):
    """Показывает итоги дня"""
    import logging
    import asyncio
    from core.garmin_data import sync_garmin_data, get_average_stats
    
    logger = logging.getLogger(__name__)
    logger.info(f"📊 /day user={message.from_user.id} ({message.from_user.first_name})")
    
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
        
        tdee = targets.get('avg_tdee', 0)
        tdee_hint = f" (тратишь ~{tdee} ккал/день)" if tdee else ""
        # Response Construction
        response_parts = [
            f"📅 <b>Итоги дня {today_formatted}</b>",
            "",
            "🥦 <b>Питание:</b>",
            f"• Калории: <b>{totals.calories:.0f}</b> / {targets['calories']} ккал{tdee_hint}",
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


import re


@router.message(Command("setup"))
async def cmd_setup(message: Message, user_id: int):
    """
    Настройка калорий для пользователей без Garmin.
    Примеры: /setup BMR 1400 активные 250
             /setup BMR 1400, активные 250, вес 60
    """
    text = (message.text or "").replace("/setup", "").strip()
    if not text:
        await message.answer(
            "⚙️ <b>Настройка целей (для пользователей без Garmin)</b>\n\n"
            "Укажи BMR и средние активные калории из Apple Health (Здоровье → Энергия):\n\n"
            "<code>/setup BMR 1400, активные 250</code>\n"
            "<code>/setup BMR 1400 активные 250 вес 60</code>\n\n"
            "• BMR — базовая энергия (ккал/день)\n"
            "• Активные — среднее сжигание от движения\n"
            "• Вес — для расчёта белков (опционально)",
            parse_mode="HTML"
        )
        return
    bmr = None
    active = None
    weight = None
    for m in re.finditer(r"(?:bmr|базовы[йе])\s*[=:]?\s*(\d+)", text, re.I):
        bmr = float(m.group(1))
        break
    if not bmr:
        for m in re.finditer(r"(\d+)\s*(?:ккал)?\s*(?:bmr|базовы)", text, re.I):
            bmr = float(m.group(1))
            break
    for m in re.finditer(r"(?:активн[ые]?|active)\s*[=:]?\s*(\d+)", text, re.I):
        active = float(m.group(1))
        break
    if not active:
        for m in re.finditer(r"(\d+)\s*(?:ккал)?\s*(?:активн|active)", text, re.I):
            active = float(m.group(1))
            break
    for m in re.finditer(r"(?:вес|weight)\s*[=:]?\s*(\d+(?:[.,]\d+)?)", text, re.I):
        weight = float(m.group(1).replace(",", "."))
        break
    if not bmr and not active and not weight:
        await message.answer("❌ Не удалось распознать BMR, активные или вес. Пример: /setup BMR 1400 активные 250")
        return
    from database import SessionLocal
    from database.crud import update_user_calorie_settings
    db = SessionLocal()
    try:
        update_user_calorie_settings(db, user_id, bmr=bmr, avg_active_calories=active, target_weight_kg=weight)
        parts = ["✅ Настройки сохранены:"]
        if bmr:
            parts.append(f"• BMR: {bmr:.0f} ккал")
        if active is not None:
            parts.append(f"• Активные: {active:.0f} ккал")
        if weight:
            parts.append(f"• Целевой вес: {weight:.1f} кг")
        parts.append(f"\nTDEE ≈ {((bmr or 1400) + (active or 0)):.0f} ккал. Цели в /day будут пересчитаны.")
        await message.answer("\n".join(parts))
    finally:
        db.close()


@router.message(Command("activity"))
async def cmd_activity(message: Message, user_id: int):
    """Логирование активных калорий за сегодня: /activity 300"""
    text = (message.text or "").replace("/activity", "").strip()
    try:
        cal = int(text) if text else 0
    except ValueError:
        cal = 0
    if cal <= 0 or cal > 3000:
        await message.answer("Использование: /activity <число> — активные калории за сегодня.\nПример: /activity 300")
        return
    from database import SessionLocal
    from database.crud import create_or_update_activity
    db = SessionLocal()
    try:
        today = datetime.now().date()
        create_or_update_activity(db, user_id, today, active_calories=float(cal), source="manual")
        await message.answer(f"✅ Активность сегодня: {cal} ккал сохранена.")
    finally:
        db.close()


@router.message(Command("burn"))
async def cmd_burn(message: Message, user_id: int):
    """Alias для /activity: /burn 300"""
    text = (message.text or "").replace("/burn", "").strip()
    try:
        cal = int(text) if text else 0
    except ValueError:
        cal = 0
    if cal <= 0 or cal > 3000:
        await message.answer("Использование: /burn <число> — активные калории за сегодня.")
        return
    from database import SessionLocal
    from database.crud import create_or_update_activity
    db = SessionLocal()
    try:
        create_or_update_activity(db, user_id, datetime.now().date(), active_calories=float(cal), source="manual")
        await message.answer(f"✅ Активность сегодня: {cal} ккал сохранена.")
    finally:
        db.close()


@router.message(Command("targets"))
async def cmd_targets(message: Message):
    """Redirect to /setup"""
    await message.answer("Используй /setup для настройки BMR и активных калорий.")



