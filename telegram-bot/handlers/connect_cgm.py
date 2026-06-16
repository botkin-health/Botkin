#!/usr/bin/env python3
"""Команда /connect_cgm — самоподключение CGM (Abbott FreeStyle Libre 3) через LibreLinkUp (#96).

Сценарий:
  1. Пользователь шлёт /connect_cgm → бот даёт инструкцию пригласить follower dr@botkin.health.
  2. Фоновая задача опрашивает get_patients() (через сервисный follower-аккаунт) и ловит
     новый patient_id, которого ещё нет в cgm_connections → привязывает к telegram_id.
  3. Дальше 5-минутный/ночной импортёр (scripts/import/librelinkup.py) тянет глюкозу.

Атрибуция: один flow за раз (asyncio-lock, бот — однопроцессный aiogram). Уже привязанные
patient_id (из cgm_connections) исключаются из кандидатов, а запись идёт идемпотентно
(unique patient_id → IntegrityError = уже занят), чтобы чужой сенсор не переназначить.
"""

import asyncio
import importlib.util
import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)
router = Router()

FOLLOWER_EMAIL = "dr@botkin.health"
POLL_INTERVAL = 30  # сек между опросами get_patients()
POLL_TIMEOUT = 600  # 10 мин ждём появления нового пациента

# Один flow подключения одновременно — иначе нельзя однозначно атрибутировать новый patient_id.
_connect_lock = asyncio.Lock()
# Держим ссылки на фоновые задачи: без этого CPython может собрать task GC до завершения.
_background_tasks: set[asyncio.Task] = set()
# Кэш загруженного по пути модуля-импортёра (не re-exec на каждом опросе).
_importer_cache = None


def detect_new_patient_ids(baseline: set[str], current: list[str]) -> list[str]:
    """Чистая функция: какие patient_id появились по сравнению с baseline (порядок сохраняется)."""
    return [pid for pid in current if pid not in baseline]


def _load_importer():
    """Загрузить scripts/import/librelinkup.py (не пакет — import зарезервирован). Кэшируется."""
    global _importer_cache
    if _importer_cache is not None:
        return _importer_cache
    path = Path(__file__).resolve().parents[2] / "scripts" / "import" / "librelinkup.py"
    spec = importlib.util.spec_from_file_location("librelinkup_import", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось загрузить импортёр LibreLinkUp из {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _importer_cache = mod
    return mod


def _fetch_patient_ids() -> list[str]:
    """Синхронный сетевой вызов: id всех пациентов, видимых follower-аккаунтом."""
    client = _load_importer().get_client()
    return [str(p.patient_id) for p in client.get_patients()]


def _mapped_patient_ids() -> set[str]:
    """patient_id, уже привязанные к кому-либо (из cgm_connections)."""
    from database import SessionLocal
    from database.models import CgmConnection

    db = SessionLocal()
    try:
        return {row.patient_id for row in db.query(CgmConnection.patient_id).all()}
    finally:
        db.close()


def _save_mapping(patient_id: str, telegram_id: int) -> bool:
    """Привязать patient_id к пользователю. False — если patient_id уже занят (idempotent)."""
    from sqlalchemy.exc import IntegrityError

    from database import SessionLocal
    from database.models import CgmConnection

    db = SessionLocal()
    try:
        db.add(CgmConnection(patient_id=patient_id, telegram_id=telegram_id))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()  # patient_id уже привязан (unique) — кто-то успел раньше
        return False
    finally:
        db.close()


async def _connect_flow(message: Message, telegram_id: int) -> None:
    """Фоновая задача: ждём новый patient_id и привязываем его к пользователю."""
    async with _connect_lock:
        loop = asyncio.get_running_loop()
        try:
            # baseline = всё, что follower видит сейчас + всё уже привязанное в БД.
            # Так чужой/ранее-подключённый сенсор не попадёт в кандидаты.
            baseline = set(await asyncio.to_thread(_fetch_patient_ids))
            baseline |= await asyncio.to_thread(_mapped_patient_ids)
        except Exception as e:
            logger.error(f"connect_cgm: ошибка старта (get_patients): {e}")
            await message.answer("⚠️ Не удалось связаться с LibreLinkUp. Попробуй позже.")
            return

        deadline = loop.time() + POLL_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                current = await asyncio.to_thread(_fetch_patient_ids)
            except Exception as e:
                logger.warning(f"connect_cgm: опрос get_patients упал, повтор: {e}")
                continue
            new_ids = detect_new_patient_ids(baseline, current)
            if not new_ids:
                continue

            patient_id = new_ids[0]
            try:
                saved = await asyncio.to_thread(_save_mapping, patient_id, telegram_id)
            except Exception as e:
                logger.error(f"connect_cgm: не смог сохранить маппинг {patient_id}: {e}")
                await message.answer("⚠️ Поймал подключение, но не смог сохранить. Напиши /connect_cgm ещё раз.")
                return
            if not saved:
                # patient_id уже занят другим пользователем — не наш, продолжаем ждать.
                baseline.add(patient_id)
                continue

            logger.info(f"connect_cgm: привязал patient {patient_id} → user {telegram_id}")
            await message.answer(
                "✅ CGM подключён! Глюкоза начнёт поступать после прогрева сенсора (~1 час).\n"
                "Дальше данные обновляются автоматически."
            )
            return

        await message.answer(
            "⏳ Не увидел приглашение за 10 минут. Проверь, что пригласил "
            f"`{FOLLOWER_EMAIL}` в LibreLinkUp, и запусти /connect_cgm ещё раз.",
            parse_mode="Markdown",
        )


@router.message(Command("connect_cgm"))
async def cmd_connect_cgm(message: Message) -> None:
    """`/connect_cgm` — подключить непрерывный мониторинг глюкозы (CGM)."""
    if _connect_lock.locked():
        await message.answer("⏳ Подключение CGM уже выполняется. Попробуй через пару минут.")
        return

    await message.answer(INSTRUCTIONS, parse_mode="Markdown")
    task = asyncio.create_task(_connect_flow(message, message.from_user.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


INSTRUCTIONS = (
    "🩸 *Подключение CGM (FreeStyle Libre 3)*\n\n"
    "1. Открой приложение *FreeStyle Libre 3* → ☰ → *Connected Apps* → *LibreLinkUp*\n"
    "2. Нажми *Invite Follower* и введи email:\n"
    f"`{FOLLOWER_EMAIL}`\n\n"
    "Я подожду до 10 минут и сам поймаю подключение — как приглашение пройдёт, "
    "напишу сюда. Глюкоза начнёт поступать после прогрева сенсора (~1 час)."
)
