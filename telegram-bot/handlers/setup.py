"""
/profile — пошаговый онбординг профиля пользователя.

Собирает: дата рождения, рост, пол, целевой вес.
Нужно для медицинских расчётов: ИМТ, PhenoAge, LE8, Framingham.

Команды:
  /profile        — начать/перезапустить заполнение профиля
  /profile_skip   — пропустить (только во время диалога)
  /profile_cancel — отменить (только во время диалога)
"""

from __future__ import annotations

import re
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

router = Router()

# ── FSM states ────────────────────────────────────────────────────────────────


class ProfileSetup(StatesGroup):
    birth_date = State()
    height = State()
    sex = State()
    target_weight = State()


# ── keyboards ─────────────────────────────────────────────────────────────────

_SEX_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="♂ Мужской"), KeyboardButton(text="♀ Женский")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_SKIP_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⏭ Пропустить")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_REMOVE_KB = ReplyKeyboardRemove()


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_date(text: str) -> date | None:
    """Парсит дату в форматах: 15.05.1977, 15/05/1977, 1977-05-15, 15 мая 1977."""
    text = text.strip()
    # ISO
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # DD.MM.YYYY or DD/MM/YYYY
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    # Russian month names: "15 мая 1977"
    months = {
        "янв": 1,
        "фев": 2,
        "мар": 3,
        "апр": 4,
        "май": 5,
        "мая": 5,
        "июн": 6,
        "июл": 7,
        "авг": 8,
        "сен": 9,
        "окт": 10,
        "ноя": 11,
        "дек": 12,
    }
    m = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text, re.IGNORECASE)
    if m:
        mon = months.get(m.group(2).lower()[:3])
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                pass
    return None


def _parse_height(text: str) -> int | None:
    """Парсит рост: '177', '177 см', '177cm', '1.77', '1,77'."""
    text = text.strip()
    # Decimal metres: 1.77 or 1,77
    m = re.match(r"^1[.,]\d{2}$", text)
    if m:
        return round(float(text.replace(",", ".")) * 100)
    # Integer cm
    m = re.match(r"^(\d{2,3})", text)
    if m:
        v = int(m.group(1))
        if 100 <= v <= 220:
            return v
    return None


def _parse_weight(text: str) -> float | None:
    """Парсит вес: '75', '75.5', '75,5', '75 кг'."""
    text = text.strip()
    m = re.match(r"^(\d{2,3}(?:[.,]\d{1,2})?)", text)
    if m:
        v = float(m.group(1).replace(",", "."))
        if 30 <= v <= 250:
            return v
    return None


def _age(birth: date) -> int:
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


# ── summary helper ────────────────────────────────────────────────────────────


def _profile_summary(data: dict) -> str:
    lines = ["✅ <b>Профиль сохранён!</b>\n"]
    if bd := data.get("birth_date"):
        lines.append(f"🎂 Дата рождения: {bd.strftime('%d.%m.%Y')} ({_age(bd)} лет)")
    if h := data.get("height_cm"):
        lines.append(f"📏 Рост: {h} см")
    if s := data.get("sex"):
        lines.append(f"⚥ Пол: {'♂ Мужской' if s == 'male' else '♀ Женский'}")
    if tw := data.get("target_weight"):
        lines.append(f"🎯 Целевой вес: {tw} кг")
    lines.append("\nДашборд теперь будет считать ИМТ, PhenoAge и Life's Essential 8 персонально.")
    return "\n".join(lines)


# ── command entrypoint ────────────────────────────────────────────────────────


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    """Начать настройку профиля."""
    # Load current values to show as defaults
    from database import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        current = {}
        if user:
            current["birth_date"] = user.birth_date
            current["height_cm"] = user.height_cm
            current["sex"] = user.sex
            current["target_weight"] = user.target_weight_kg
    finally:
        db.close()

    await state.set_state(ProfileSetup.birth_date)
    await state.update_data(current=current)

    hint = ""
    if current.get("birth_date"):
        hint = f"\nТекущее: <code>{current['birth_date'].strftime('%d.%m.%Y')}</code> — отправь новое или /profile_skip"

    await message.answer(
        "👤 <b>Настройка профиля</b> (шаг 1/4)\n\n"
        "🎂 <b>Дата рождения</b> — нужна для расчёта биологического возраста (PhenoAge).\n\n"
        "Формат: <code>15.05.1977</code> или <code>1977-05-15</code>" + hint,
        parse_mode="HTML",
        reply_markup=_SKIP_KB if current.get("birth_date") else _REMOVE_KB,
    )


# ── cancel / skip ─────────────────────────────────────────────────────────────


@router.message(Command("profile_cancel"))
async def cmd_profile_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Настройка профиля отменена.", reply_markup=_REMOVE_KB)


@router.message(Command("profile_skip"))
async def cmd_profile_skip(message: Message, state: FSMContext):
    """Пропустить текущий шаг — сохраняет старое значение."""
    current_state = await state.get_state()
    if not current_state or not current_state.startswith("ProfileSetup:"):
        await message.answer("Нет активного диалога настройки. Начни с /profile.")
        return
    data = await state.get_data()
    current = data.get("current", {})

    if current_state == ProfileSetup.birth_date:
        await state.update_data(birth_date=current.get("birth_date"))
        await _ask_height(message, state, current)
    elif current_state == ProfileSetup.height:
        await state.update_data(height_cm=current.get("height_cm"))
        await _ask_sex(message, state, current)
    elif current_state == ProfileSetup.sex:
        await state.update_data(sex=current.get("sex"))
        await _ask_target_weight(message, state, current)
    elif current_state == ProfileSetup.target_weight:
        await state.update_data(target_weight=current.get("target_weight"))
        await _save_profile(message, state)


# ── step 1: birth_date ────────────────────────────────────────────────────────


@router.message(ProfileSetup.birth_date)
async def step_birth_date(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    # Allow skip via button
    if text in ("⏭ Пропустить", "/profile_skip"):
        return await cmd_profile_skip(message, state)

    bd = _parse_date(text)
    if not bd:
        await message.answer(
            "❌ Не понял дату. Попробуй формат: <code>15.05.1977</code>",
            parse_mode="HTML",
        )
        return

    if bd.year < 1920 or bd >= date.today():
        await message.answer("❌ Дата выглядит неправильной. Проверь и попробуй снова.")
        return

    await state.update_data(birth_date=bd)
    data = await state.get_data()
    await _ask_height(message, state, data.get("current", {}))


async def _ask_height(message: Message, state: FSMContext, current: dict):
    await state.set_state(ProfileSetup.height)
    hint = (
        f"\nТекущее: <code>{current['height_cm']} см</code> — отправь новое или /profile_skip"
        if current.get("height_cm")
        else ""
    )
    await message.answer(
        "👤 <b>Настройка профиля</b> (шаг 2/4)\n\n"
        "📏 <b>Рост в см</b> — нужен для расчёта ИМТ.\n\n"
        "Пример: <code>177</code>" + hint,
        parse_mode="HTML",
        reply_markup=_SKIP_KB if current.get("height_cm") else _REMOVE_KB,
    )


# ── step 2: height ────────────────────────────────────────────────────────────


@router.message(ProfileSetup.height)
async def step_height(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in ("⏭ Пропустить", "/profile_skip"):
        return await cmd_profile_skip(message, state)

    h = _parse_height(text)
    if not h:
        await message.answer("❌ Не понял рост. Укажи в сантиметрах, например: <code>177</code>", parse_mode="HTML")
        return

    await state.update_data(height_cm=h)
    data = await state.get_data()
    await _ask_sex(message, state, data.get("current", {}))


async def _ask_sex(message: Message, state: FSMContext, current: dict):
    await state.set_state(ProfileSetup.sex)
    current_label = ""
    if current.get("sex"):
        label = "♂ Мужской" if current["sex"] == "male" else "♀ Женский"
        current_label = f"\nТекущее: {label}"
    await message.answer(
        "👤 <b>Настройка профиля</b> (шаг 3/4)\n\n"
        "⚥ <b>Пол</b> — влияет на референсные диапазоны анализов и модель риска Framingham." + current_label,
        parse_mode="HTML",
        reply_markup=_SEX_KB,
    )


# ── step 3: sex ───────────────────────────────────────────────────────────────


@router.message(ProfileSetup.sex)
async def step_sex(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in ("⏭ Пропустить", "/profile_skip"):
        return await cmd_profile_skip(message, state)

    text_lower = text.lower()
    if any(w in text_lower for w in ("муж", "male", "м", "♂")):
        sex = "male"
    elif any(w in text_lower for w in ("жен", "female", "ж", "♀")):
        sex = "female"
    else:
        await message.answer("Выбери из кнопок: ♂ Мужской или ♀ Женский.", reply_markup=_SEX_KB)
        return

    await state.update_data(sex=sex)
    data = await state.get_data()
    await _ask_target_weight(message, state, data.get("current", {}))


async def _ask_target_weight(message: Message, state: FSMContext, current: dict):
    await state.set_state(ProfileSetup.target_weight)
    hint = (
        f"\nТекущее: <code>{current['target_weight']} кг</code> — отправь новое или /profile_skip"
        if current.get("target_weight")
        else ""
    )
    await message.answer(
        "👤 <b>Настройка профиля</b> (шаг 4/4)\n\n"
        "🎯 <b>Целевой вес в кг</b> — показывается на дашборде как прогресс-бар.\n\n"
        "Пример: <code>72</code>" + hint,
        parse_mode="HTML",
        reply_markup=_SKIP_KB if current.get("target_weight") else _REMOVE_KB,
    )


# ── step 4: target_weight ─────────────────────────────────────────────────────


@router.message(ProfileSetup.target_weight)
async def step_target_weight(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in ("⏭ Пропустить", "/profile_skip"):
        return await cmd_profile_skip(message, state)

    tw = _parse_weight(text)
    if not tw:
        await message.answer("❌ Не понял вес. Укажи в кг, например: <code>72</code>", parse_mode="HTML")
        return

    await state.update_data(target_weight=tw)
    await _save_profile(message, state)


# ── save ──────────────────────────────────────────────────────────────────────


async def _save_profile(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    birth_date = data.get("birth_date")
    height_cm = data.get("height_cm")
    sex = data.get("sex")
    target_weight = data.get("target_weight")

    from database import SessionLocal
    from database.models import User, UserSettings

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            await message.answer("❌ Пользователь не найден.", reply_markup=_REMOVE_KB)
            return

        if birth_date is not None:
            user.birth_date = birth_date
        if height_cm is not None:
            user.height_cm = height_cm
        if sex is not None:
            user.sex = sex
        if target_weight is not None:
            user.target_weight_kg = target_weight
            # Also sync to user_settings if exists
            settings = db.query(UserSettings).filter_by(user_id=user.telegram_id).first()
            if settings:
                settings.target_weight_kg = target_weight

        db.commit()

        await message.answer(
            _profile_summary(data),
            parse_mode="HTML",
            reply_markup=_REMOVE_KB,
        )
    except Exception as e:
        db.rollback()
        await message.answer(f"❌ Ошибка сохранения: {e}", reply_markup=_REMOVE_KB)
    finally:
        db.close()
