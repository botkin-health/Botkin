#!/usr/bin/env python3
"""
Обработчик команды /sync — внеплановый запуск pull-source синхронизаций.

Сценарий: пользователь только что закончил тренировку в Garmin или взвесился
на Mi-весах → не хочет ждать ночного cron, пишет /sync и через минуту видит
свежие данные.

Pull-sources (нужен явный sync):
- Garmin — `scripts/garmin/download_garmin_data.py`
- Netatmo — `scripts/import/netatmo.py`
- Weather — `scripts/import/weather.py`
- Zepp — `scripts/import/zepp_api.py` (когда токен живой)

Push-sources (приходят сами, sync не нужен):
- Apple Health — HAE webhook
- Сообщения в боте — пишутся при отправке

Использование:
- `/sync` — все pull-источники последовательно
- `/sync garmin` / `/sync netatmo` / `/sync weather` / `/sync zepp` — один
- `/sync status` — таблица «когда последний раз отработало успешно»

MVP-ограничения:
- Только admin может запускать (расширим на всех когда per-user creds готовы)
- Кулдаун 5 минут между ручными запусками одного источника (нагрузка на API)
- Таймаут на источник 5 минут (Garmin может качать долго)
"""

import asyncio
import logging
import re
import time
from pathlib import Path

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandObject

from config.users import is_admin

router = Router()
logger = logging.getLogger(__name__)

# Кулдауны: {source_name: last_run_timestamp}
_LAST_RUN: dict[str, float] = {}
COOLDOWN_SECONDS = 300  # 5 минут между ручными синками одного источника

# Исходы синка одного источника — человекочитаемая классификация для отчёта (#138).
OUTCOME_OK = "ok"  # обновлено, есть свежие данные
OUTCOME_NOOP = "noop"  # отработал, но новых данных не было
OUTCOME_UNAVAILABLE = "unavailable"  # внешний сервис временно недоступен — данные не потеряны
OUTCOME_ERROR = "error"  # внутренняя ошибка — детали только в серверном логе

OUTCOME_ICON = {
    OUTCOME_OK: "✅",
    OUTCOME_NOOP: "➖",
    OUTCOME_UNAVAILABLE: "⏳",
    OUTCOME_ERROR: "⚠️",
}

# Исходы, при которых данные пользователя в порядке (свежие или просто без обновлений).
_GOOD_OUTCOMES = (OUTCOME_OK, OUTCOME_NOOP)

# Маркеры в выводе успешного скрипта: «отработал, но тянуть было нечего».
_NOOP_MARKERS = (
    "новых данных нет",
    "нет новых",
    "ничего нового",
    "уже актуал",
    "актуально",
    "up to date",
    "no new",
    "0 new",
    "nothing to",
    "no updates",
)

# Маркеры временной недоступности внешнего сервиса (сеть / HTTP / rate-limit).
_TEMPORARY_MARKERS = (
    "connectionerror",
    "connection aborted",
    "connection reset",
    "connection refused",
    "max retries",
    "newconnectionerror",
    "failed to establish",
    "timeouterror",
    "timed out",
    "timeout",
    "read timed out",
    "temporarily unavailable",
    "service unavailable",
    "gaierror",
    "name or service not known",
    "cloudflare",
    "sslerror",
    "недоступ",
)

# HTTP-коды временных сбоев (rate-limit / серверные / Libre 476). Ловим как
# отдельный токен по границе слова, чтобы не сматчить число внутри пути/ID.
_TEMPORARY_HTTP_RE = re.compile(r"\b(408|425|429|476|500|502|503|504)\b")

# Карта sources: name → (script path в контейнере, человекочитаемое имя,
#                       glob-pattern для freshness — mtime самого свежего матча).
# Берём mtime data-файлов (а не log-файлов на хосте — бот их не видит изнутри
# контейнера), это семантически эквивалентно «когда данные обновлялись».
SOURCES = {
    "weather": (
        "/app/scripts/import/weather.py",
        "Погода (Open-Meteo)",
        "/app/data/weather/weather_history.json",
    ),
    "netatmo": (
        "/app/scripts/import/netatmo.py",
        "Netatmo (воздух дома)",
        "/app/data/environment/netatmo_history.json",
    ),
    # Derived-builder: пересобирает env_data_{user_id}.json для блока
    # «Воздух дома» на дашборде. Должен идти ПОСЛЕ netatmo. Симметрично
    # workouts. Без этого шага дашборд отставал — баг найден 24.05.2026.
    "env": (
        "/app/scripts/util/build_env_data.py",
        "Воздух дома (дашборд)",
        "/app/telegram-bot/env_data_895655.json",
    ),
    "garmin": (
        "/app/scripts/garmin/download_garmin_data.py",
        "Garmin (часы)",
        "/app/data/garmin/daily-summary/*.json",
    ),
    # Derived-builder: пересобирает workouts_log_{user_id}.json из сырых
    # Garmin-активностей. Должен идти ПОСЛЕ garmin (зависит от его выхода).
    # Иначе дашборд читает устаревший derived-файл — баг, который и привёл
    # к появлению этого ключа (см. история 24.05.2026 — тренировка 22.05
    # была в сырых данных, но не в дашборде).
    "workouts": (
        "/app/scripts/util/build_workouts_log.py",
        "Workouts (дашборд)",
        "/app/telegram-bot/workouts_log_895655.json",
    ),
    # Postgres backfill: workouts + sleep + hrv → таблицы для агента
    # (/recent_workouts, /recent_activity). Должен идти ПОСЛЕ garmin
    # (читает /app/data/garmin/*). Без этого шага агент-БД отстаёт от
    # дашборда даже если /sync workouts успешно пересобрал JSON.
    # См. ADR-like запись в DEV_LOG 24.05.2026.
    "pg_sync": (
        "/app/scripts/util/server_backfill_postgres.py",
        "Postgres (агент)",
        "/app/data/cache/pg_sync_last_run.json",
    ),
    "zepp": (
        "/app/scripts/import/zepp_api.py",
        "Zepp (весы)",
        "/app/data/zepp_export_latest.csv",
    ),
    # CGM-глюкоза (Abbott Libre 3 → LibreLinkUp). Пишет в БД glucose_readings,
    # файла свежести нет → в /sync status покажет "—". См. #96/#129.
    "glucose": (
        "/app/scripts/import/librelinkup.py",
        "Глюкоза (CGM)",
        None,
    ),
}


def _looks_noop(output: str) -> bool:
    """Похоже ли, что успешный скрипт ничего нового не подтянул."""
    low = output.lower()
    return any(marker in low for marker in _NOOP_MARKERS)


def _looks_temporary(output: str) -> bool:
    """Похож ли провал на временную недоступность внешнего сервиса (сеть/HTTP)."""
    low = output.lower()
    if any(marker in low for marker in _TEMPORARY_MARKERS):
        return True
    return bool(_TEMPORARY_HTTP_RE.search(output))


def _classify_success(output: str) -> tuple[str, str]:
    """rc==0: различить «обновлено» и «новых данных не было»."""
    if _looks_noop(output):
        return OUTCOME_NOOP, "актуально, новых данных нет"
    return OUTCOME_OK, "обновлено"


def _classify_failure(source_key: str, output: str) -> tuple[str, str]:
    """rc!=0 / исключение: временная недоступность сервиса vs внутренняя ошибка.

    Возвращает ТОЛЬКО дружелюбный текст — без traceback/Errno/внутренних путей.
    Сырой вывод пишет в серверный лог вызывающая сторона (`_run_script`).
    """
    if _looks_temporary(output):
        if source_key == "glucose":
            return OUTCOME_UNAVAILABLE, "сервис Abbott временно недоступен, подтянем автоматически позже"
        return OUTCOME_UNAVAILABLE, "сервис временно недоступен, подтянем автоматически позже"
    return OUTCOME_ERROR, "не удалось обновить — записал в журнал, разберёмся"


async def _run_script(source_key: str, script_path: str, timeout: int = 300) -> tuple[str, str]:
    """Запускает скрипт источника и классифицирует исход (см. #138).

    Возвращает (outcome, friendly_detail). Сырой вывод/traceback уходит ТОЛЬКО
    в серверный лог — пользователю показывается короткий человекочитаемый текст.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "python",
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("sync %s: таймаут %sс", source_key, timeout)
            return OUTCOME_UNAVAILABLE, "долго отвечает — подтянем автоматически позже"

        output = (stdout or b"").decode("utf-8", errors="replace")
        if proc.returncode == 0:
            return _classify_success(output)

        # Провал: сырой вывод — только в серверный лог, пользователю — friendly-текст.
        logger.warning("sync %s: exit=%s\n%s", source_key, proc.returncode, output)
        return _classify_failure(source_key, output)
    except FileNotFoundError as e:
        logger.error("sync %s: скрипт не найден: %s", source_key, e)
        return OUTCOME_ERROR, "не удалось обновить — записал в журнал, разберёмся"
    except Exception:
        logger.exception("sync %s: неожиданная ошибка", source_key)
        return OUTCOME_ERROR, "не удалось обновить — записал в журнал, разберёмся"


def _format_log_mtime(pattern: str | None) -> str:
    """Возвращает 'YYYY-MM-DD HH:MM' от mtime самого свежего файла, матчащего pattern.

    Pattern может быть точным путём ('/app/data/weather/weather_history.json')
    или glob-маской ('/app/data/garmin/daily-summary/*.json').
    """
    if not pattern:
        return "—"

    import datetime
    import glob

    matches = glob.glob(pattern)
    if not matches:
        return "—"

    # Берём самый свежий по mtime
    newest = max(matches, key=lambda p: Path(p).stat().st_mtime)
    mtime = datetime.datetime.fromtimestamp(Path(newest).stat().st_mtime)
    return mtime.strftime("%Y-%m-%d %H:%M")


@router.message(Command("sync"))
async def cmd_sync(message: Message, command: CommandObject, user_id: int):
    """`/sync` — запустить pull-синхронизации.

    Без аргументов — все источники.
    С аргументом — один (`/sync garmin`).
    `/sync status` — показать когда последний раз отработало.
    """
    # MVP: только admin
    if not is_admin(user_id):
        await message.answer(
            "🔒 Команда `/sync` пока доступна только админу.\n"
            "Когда введём per-user креды для Garmin/Zepp — открою всем.",
            parse_mode="Markdown",
        )
        return

    arg = (command.args or "").strip().lower()

    # /sync status
    if arg == "status":
        rows = ["📊 *Последний успешный sync:*\n"]
        for name, (_, label, log) in SOURCES.items():
            rows.append(f"• {label}: `{_format_log_mtime(log)}`")
        rows.append("\n_Apple Health и сообщения боту приходят сами (push) — sync не нужен._")
        await message.answer("\n".join(rows), parse_mode="Markdown")
        return

    # /sync <source> или /sync
    if arg and arg in SOURCES:
        sources_to_run = [arg]
    elif arg:
        await message.answer(
            f"❓ Не знаю источник `{arg}`.\nДоступные: {', '.join(SOURCES.keys())}, или `/sync status`.",
            parse_mode="Markdown",
        )
        return
    else:
        sources_to_run = list(SOURCES.keys())

    # Кулдаун
    now = time.time()
    cooldown_skipped = []
    actually_run = []
    for src in sources_to_run:
        last = _LAST_RUN.get(src, 0)
        if now - last < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - (now - last))
            cooldown_skipped.append((src, remaining))
        else:
            actually_run.append(src)

    if not actually_run:
        msg = "⏳ Все источники запущены недавно. Подожди:\n"
        for src, sec in cooldown_skipped:
            msg += f"• {SOURCES[src][1]} — {sec}с\n"
        await message.answer(msg)
        return

    # Старт-сообщение (одной строкой — лаконично)
    short_labels = ", ".join(SOURCES[s][1].split(" ")[0] for s in actually_run)
    progress_msg = await message.answer(f"🔄 Sync: {short_labels}…")

    # Запуск последовательно (Garmin самый долгий, параллельность не критична)
    started = time.time()
    results: list[tuple[str, str, str, str]] = []  # (src, label, outcome, detail)
    for src in actually_run:
        script, label, _ = SOURCES[src]
        _LAST_RUN[src] = time.time()
        outcome, detail = await _run_script(src, script)
        results.append((src, label, outcome, detail))

    elapsed = int(time.time() - started)
    elapsed_str = f"{elapsed}с" if elapsed < 60 else f"{elapsed // 60}м {elapsed % 60}с"

    ok_count = sum(1 for _, _, outcome, _ in results if outcome in _GOOD_OUTCOMES)
    total = len(results)

    # Header
    if ok_count == total:
        lines = [f"✅ Sync чисто ({elapsed_str}) · все {total} источника обновлены"]
    elif ok_count == 0:
        lines = [f"❌ Sync упал ({elapsed_str}) · 0/{total}"]
    else:
        lines = [f"🔄 Sync ({elapsed_str}) · {ok_count}/{total} ✅"]

    # OK sources — одной строкой через ·
    ok_labels = [label for _, label, outcome, _ in results if outcome in _GOOD_OUTCOMES]
    if ok_labels:
        # Сокращённые имена для одной строки (убираем "(...)" в скобках)
        short = [lbl.split(" (")[0] for lbl in ok_labels]
        lines.append("\n✅ " + " · ".join(short))

    # Failures — каждая отдельной строкой с дружелюбной причиной
    failures = [(label, detail) for _, label, outcome, detail in results if outcome not in _GOOD_OUTCOMES]
    for label, detail in failures:
        short_label = label.split(" (")[0]
        lines.append(f"❌ {short_label} — {detail}")

    if cooldown_skipped:
        skipped = ", ".join(SOURCES[s][1].split(" (")[0] for s, _ in cooldown_skipped)
        lines.append(f"\n⏳ Пропущено (кулдаун): {skipped}")

    summary = "\n".join(lines)
    if len(summary) > 3900:
        summary = summary[:3900] + "\n\n…[обрезано]"

    # Заменяем progress-сообщение финальным.
    # parse_mode=None ОБЯЗАТЕЛЕН: сводка — plain text (emoji + текст), но текст ошибки
    # источника может содержать «<...>» (напр. LibreLinkUp 476: «… <none> for url …»).
    # Бот по умолчанию шлёт HTML → Telegram падает на «Unsupported start tag "none"»,
    # и edit_text, и fallback answer → сводка не доставляется, прогресс висит вечно (#157).
    try:
        await progress_msg.edit_text(summary, parse_mode=None)
    except Exception:
        # Если редактирование не удалось — пошлём новое
        await message.answer(summary, parse_mode=None)
