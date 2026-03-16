#!/usr/bin/env python3
"""
Обработчик команд бота (/start, /help, /day, /week, /vitamins и т.д.)
"""

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))

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
        "/my_products — мои продукты (подстановка КБЖУ без нейросети)\n"
        "/add_product — добавить продукт\n"
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
        "<i>💡 Называйте прием (Завтрак/Ужин) или учту текущее время. Это для контроля углеводов.</i>\n"
        "<i>💡 Уточняйте: 'вареная гречка', 'сухой рис', 'готовая паста' — иначе бот считает как сухой продукт.</i>\n\n"
        "💊 <b>Витамины и Лекарства:</b>\n"
        "📸 <b>Фото:</b> Таблетки на ладони или упаковки.\n"
        "🗣 <b>Голос:</b> 'Выпил утренние', 'Принял нурофен'.\n"
        "📝 <b>Текст:</b> 'Омега и Д3 плюс'.\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/day [дата] — Итоги дня (можно 'вчера' или '26.02').\n"
        "/vitamins — Чек-лист и схема приема.\n"
        "/week — Анализ рациона за неделю.\n"
        "/setup — Настройка BMR и активных ккал (без Garmin).\n"
        "/activity &lt;число&gt; — Ввести активные калории за сегодня вручную.\n"
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
        
        real_today = datetime.now(MSK).date()
        today_date = real_today
        
        # Check if user asked for a specific date
        text = message.text.lower() if message.text else ""
        if "вчера" in text or "yesterday" in text:
            today_date -= timedelta(days=1)
        else:
            parts = text.split()
            if len(parts) > 1:
                date_str = parts[1]
                for fmt in ('%d.%m', '%d.%m.%Y', '%Y-%m-%d'):
                    try:
                        parsed = datetime.strptime(date_str, fmt).date()
                        if fmt == '%d.%m':
                            parsed = parsed.replace(year=today_date.year)
                        today_date = parsed
                        break
                    except ValueError:
                        pass
        
        today_str = today_date.strftime('%Y-%m-%d')
        today_formatted = today_date.strftime('%d.%m.%Y')
        activity_label = "сегодня" if today_date == real_today else today_formatted
        
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
        
        # --- Energy balance (14-day averages → consistent with target calculation) ---
        from database.crud import get_average_activity_stats
        from core.caloric_budget import make_macro_bar, make_block_bar
        avg_stats = get_average_activity_stats(db, user_id, days=14)
        avg_bmr    = round(avg_stats.get('bmr_calories',    0)) if avg_stats else 0
        avg_active = round(avg_stats.get('active_calories', 0)) if avg_stats else 0
        avg_total  = round(avg_stats.get('total_calories',  0)) if avg_stats else 0
        today_active_r = round(active_calories)
        target_cal = targets['calories']

        deficit_pct = round((1 - 0.85) * 100)  # 15%
        if avg_total > 1500:
            active_line = f"🏃 {today_active_r} ккал сегодня · {avg_active} в среднем"
            energy_line = (
                f"💤 {avg_bmr} ккал — базовый расход\n"
                f"{active_line}\n"
                f"🎯 {target_cal} ккал — цель (дефицит −{deficit_pct}%)"
            )
        else:
            energy_line = (
                f"🏃 {today_active_r} ккал — активность сегодня\n"
                f"🎯 {target_cal} ккал — цель (дефицит −{deficit_pct}%)"
            )

        # --- Calorie bar ---
        cal_bar, cal_pct = make_block_bar(totals.calories, target_cal)
        cal_remaining = target_cal - round(totals.calories)
        if cal_remaining < 0:
            cal_tail = f"перебор +{abs(cal_remaining)}"
        else:
            cal_tail = f"ост. {cal_remaining}"

        # --- Macro bars ---
        p_bar, p_pct = make_block_bar(totals.protein, targets['protein'], invert=True)
        f_bar, f_pct = make_block_bar(totals.fats,    targets['fats'])
        c_bar, c_pct = make_block_bar(totals.carbs,   targets['carbs'])

        # --- Fiber (optional, norm 30g) ---
        fiber_val = getattr(totals, 'fiber', 0) or 0
        fiber_line = ""
        if fiber_val > 0:
            fib_bar, fib_pct = make_block_bar(fiber_val, 30, invert=True)
            fiber_line = f"🌿 {fib_bar} {fib_pct}% · {fiber_val:.0f}/30г"

        # --- Response Construction ---
        response_parts = [
            f"📅 <b>Итоги дня {today_formatted}</b>",
            "",
            energy_line,
            "",
            f"{cal_bar} {round(totals.calories):.0f} / {target_cal} ккал · {cal_tail}",
            "",
            f"Б {p_bar} {totals.protein:.0f}/{targets['protein']}г",
            f"Ж {f_bar} {totals.fats:.0f}/{targets['fats']}г",
            f"У {c_bar} {totals.carbs:.0f}/{targets['carbs']}г",
        ]
        if fiber_line:
            response_parts.append(fiber_line)

        # Weight and supplements
        response_parts.append("")
        if weight_text:
            response_parts.append(weight_text)
        response_parts.append(supplements_text)

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
            candidate = float(m.group(1))
            if bmr is None or candidate != bmr:  # не подставлять BMR за активные
                active = candidate
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
        today = datetime.now(MSK).date()
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
        create_or_update_activity(db, user_id, datetime.now(MSK).date(), active_calories=float(cal), source="manual")
        await message.answer(f"✅ Активность сегодня: {cal} ккал сохранена.")
    finally:
        db.close()


@router.message(Command("targets"))
async def cmd_targets(message: Message):
    """Redirect to /setup"""
    await message.answer("Используй /setup для настройки BMR и активных калорий.")


@router.message(Command("my_products"))
async def cmd_my_products(message: Message, user_id: int):
    """Список моих продуктов"""
    from database import SessionLocal, get_user_products
    db = SessionLocal()
    try:
        products = get_user_products(db, user_id)
        if not products:
            await message.answer("📋 У тебя пока нет сохранённых продуктов.\nДобавь: /add_product")
            return
        lines = ["📋 <b>Мои продукты:</b>\n"]
        for p in products:
            line = f"• id{p.id} <b>{p.name}</b> — {p.calories_per_100g:.0f} ккал/100г (Б:{p.protein_per_100g:.0f} Ж:{p.fats_per_100g:.0f} У:{p.carbs_per_100g:.0f})"
            if p.default_portion_g:
                line += f", порция {p.default_portion_g:.0f}г"
            if p.aliases:
                line += f"\n  Алиасы: {', '.join(p.aliases)}"
            lines.append(line)
        await message.answer("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


@router.message(Command("add_product"))
async def cmd_add_product(message: Message, user_id: int):
    """
    Добавить продукт: КБЖУ на 100г, алиасы, порция.
    Пример: /add_product Boombar батончик | 400 20 15 45 | порция 50 | алиасы: бумбар, бум бар
    Или: /add_product Сыворочный протеин | 400 80 5 5 | порция 30 | алиасы: протеин, сыворочный
    """
    import re
    text = (message.text or "").replace("/add_product", "").strip()
    if not text:
        await message.answer(
            "📌 <b>Добавить свой продукт</b> (бот будет подставлять КБЖУ без нейросети):\n\n"
            "<code>/add_product Название | ккал б ж у [порция Nг] [алиасы: a, b]</code>\n\n"
            "Пример:\n"
            "<code>/add_product Boombar | 400 20 15 45 | порция 50 | алиасы: бумбар, бум бар</code>\n"
            "<code>/add_product Сыворочный протеин | 400 80 5 5 | порция 30 | алиасы: протеин</code>",
            parse_mode="HTML"
        )
        return
    parts = [p.strip() for p in text.split("|")]
    name = parts[0].strip() if parts else ""
    if not name:
        await message.answer("❌ Укажи название продукта.")
        return
    # КБЖУ: второе поле или из первого числа
    kcal, protein, fats, carbs = None, None, None, None
    if len(parts) >= 2:
        nums = re.findall(r"[\d.,]+", parts[1])
        if len(nums) >= 4:
            kcal, protein, fats, carbs = float(nums[0].replace(",", ".")), float(nums[1].replace(",", ".")), float(nums[2].replace(",", ".")), float(nums[3].replace(",", "."))
    if kcal is None:
        nums = re.findall(r"[\d.,]+", text)
        if len(nums) >= 4:
            kcal, protein, fats, carbs = float(nums[0].replace(",", ".")), float(nums[1].replace(",", ".")), float(nums[2].replace(",", ".")), float(nums[3].replace(",", "."))
    if kcal is None:
        await message.answer("❌ Укажи КБЖУ на 100г: ккал белки жиры углеводы (четыре числа).")
        return
    default_portion = None
    aliases = None
    for p in parts[1:]:
        if re.search(r"порция\s*(\d+(?:[.,]\d+)?)\s*г?", p, re.I):
            m = re.search(r"(\d+(?:[.,]\d+)?)", p)
            if m:
                default_portion = float(m.group(1).replace(",", "."))
        if "алиасы" in p.lower() or "алиас" in p.lower():
            raw = re.sub(r"алиасы?\s*:\s*", "", p, flags=re.I).strip()
            aliases = [a.strip() for a in re.split(r"[,;]", raw) if a.strip()]
    from database import SessionLocal, add_user_product
    db = SessionLocal()
    try:
        add_user_product(
            db, user_id, name,
            calories_per_100g=kcal, protein_per_100g=protein, fats_per_100g=fats, carbs_per_100g=carbs,
            aliases=aliases, default_portion_g=default_portion
        )
        msg = f"✅ Продукт «{name}» добавлен. КБЖУ на 100г: {kcal:.0f} / {protein:.0f} / {fats:.0f} / {carbs:.0f}"
        if default_portion:
            msg += f", порция {default_portion:.0f}г"
        if aliases:
            msg += f". Алиасы: {', '.join(aliases)}"
        await message.answer(msg)
    finally:
        db.close()


@router.message(Command("add_variant"))
async def cmd_add_variant(message: Message, user_id: int):
    """
    Добавить вариант продукта (для среднего КБЖУ). После добавления вариантов КБЖУ продукта пересчитается как среднее.
    Пример: /add_variant 1 | MyProtein сыворотка | 410 82 4 6
    (1 — id продукта из списка /my_products, можно не указывать id если продукт один с таким именем)
    """
    text = (message.text or "").replace("/add_variant", "").strip()
    if not text:
        await message.answer(
            "📌 <b>Добавить вариант продукта</b> (среднее КБЖУ):\n\n"
            "<code>/add_variant [id продукта] | Название варианта | ккал б ж у</code>\n\n"
            "Пример: /add_variant 1 | Протеин Optimum | 400 80 5 5",
            parse_mode="HTML"
        )
        return
    from database import SessionLocal, get_user_products, add_product_variant, update_product_average_from_variants
    import re
    parts = [p.strip() for p in text.split("|")]
    product_id = None
    if len(parts) >= 1 and parts[0].isdigit():
        product_id = int(parts[0])
        parts = parts[1:]
    if len(parts) < 2:
        await message.answer("❌ Укажи название варианта и КБЖУ на 100г (ккал б ж у).")
        return
    name = parts[0]
    nums = re.findall(r"[\d.,]+", parts[1])
    if len(nums) < 4:
        await message.answer("❌ Нужны четыре числа: ккал, белки, жиры, углеводы на 100г.")
        return
    kcal, protein, fats, carbs = float(nums[0].replace(",", ".")), float(nums[1].replace(",", ".")), float(nums[2].replace(",", ".")), float(nums[3].replace(",", "."))
    db = SessionLocal()
    try:
        if product_id is None:
            products = get_user_products(db, user_id)
            if len(products) != 1:
                await message.answer("❌ Укажи id продукта: /add_variant <id> | ... (список: /my_products)")
                return
            product_id = products[0].id
        add_product_variant(db, product_id, name, kcal, protein, fats, carbs)
        update_product_average_from_variants(db, product_id)
        await message.answer(f"✅ Вариант «{name}» добавлен. КБЖУ продукта пересчитаны как среднее.")
    finally:
        db.close()


