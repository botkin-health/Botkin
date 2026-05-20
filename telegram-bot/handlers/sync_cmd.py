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
import time
from pathlib import Path

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandObject

from config.users import is_admin

router = Router()

# Кулдауны: {source_name: last_run_timestamp}
_LAST_RUN: dict[str, float] = {}
COOLDOWN_SECONDS = 300  # 5 минут между ручными синками одного источника

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
    "garmin": (
        "/app/scripts/garmin/download_garmin_data.py",
        "Garmin (часы)",
        "/app/data/garmin/daily-summary/*.json",
    ),
    "zepp": (
        "/app/scripts/import/zepp_api.py",
        "Zepp (весы)",
        "/app/data/zepp_export_latest.csv",
    ),
}


async def _run_script(script_path: str, timeout: int = 300) -> tuple[bool, str]:
    """Запускает Python-скрипт в текущем процессе бота (мы уже в контейнере).

    Возвращает (success, summary) — для упавшего скрипта это короткая
    причина (одна осмысленная строка), для успешного — пустая строка.
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
            return False, f"таймаут {timeout}с"

        output = (stdout or b"").decode("utf-8", errors="replace")
        if proc.returncode == 0:
            return True, ""

        # Failure: выбрать одну информативную строку для пользователя
        return False, _summarize_error(output)
    except FileNotFoundError as e:
        return False, f"скрипт не найден: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _summarize_error(stderr_output: str) -> str:
    """Извлекает одну читабельную строку из stdout/stderr упавшего скрипта.

    Стратегия (по приоритету):
      1. Последняя строка Traceback («ModuleNotFoundError: ...», «401 ...»)
      2. Строка с «Error», «error», «Exception», «failed», «401», «403», «500»
      3. Просто последняя непустая строка

    Обрезает до 200 символов чтобы влезло в общий summary.
    """
    lines = [line.strip() for line in stderr_output.strip().split("\n") if line.strip()]
    if not lines:
        return "пустой вывод (exit != 0)"

    # 1. Tail of Traceback — usually the actual error type+msg
    for line in reversed(lines):
        if any(
            line.startswith(prefix)
            for prefix in (
                "ModuleNotFoundError",
                "ImportError",
                "ConnectionError",
                "TimeoutError",
                "ValueError",
                "KeyError",
                "AttributeError",
                "TypeError",
                "RuntimeError",
                "OSError",
                "FileNotFoundError",
            )
        ):
            return line[:200]

    # 2. Any line with error-ish keywords
    for line in reversed(lines):
        low = line.lower()
        if any(kw in low for kw in ("error:", "exception:", "failed", "401", "403", "500", "❌", "⚠")):
            # Strip leading "❌ " etc emoji noise
            return line[:200]

    # 3. Just the last non-trivial line
    return lines[-1][:200]


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
    results: list[tuple[str, str, bool, str]] = []  # (src, label, success, error_summary)
    for src in actually_run:
        script, label, _ = SOURCES[src]
        _LAST_RUN[src] = time.time()
        success, err_summary = await _run_script(script)
        results.append((src, label, success, err_summary))

    elapsed = int(time.time() - started)
    elapsed_str = f"{elapsed}с" if elapsed < 60 else f"{elapsed // 60}м {elapsed % 60}с"

    ok_count = sum(1 for _, _, s, _ in results if s)
    total = len(results)

    # Header
    if ok_count == total:
        lines = [f"✅ Sync чисто ({elapsed_str}) · все {total} источника обновлены"]
    elif ok_count == 0:
        lines = [f"❌ Sync упал ({elapsed_str}) · 0/{total}"]
    else:
        lines = [f"🔄 Sync ({elapsed_str}) · {ok_count}/{total} ✅"]

    # OK sources — одной строкой через ·
    ok_labels = [label for _, label, success, _ in results if success]
    if ok_labels:
        # Сокращённые имена для одной строки (убираем "(...)" в скобках)
        short = [lbl.split(" (")[0] for lbl in ok_labels]
        lines.append("\n✅ " + " · ".join(short))

    # Failures — каждая отдельной строкой с причиной
    failures = [(label, err) for _, label, success, err in results if not success]
    for label, err in failures:
        short_label = label.split(" (")[0]
        lines.append(f"❌ {short_label} — {err}")

    if cooldown_skipped:
        skipped = ", ".join(SOURCES[s][1].split(" (")[0] for s, _ in cooldown_skipped)
        lines.append(f"\n⏳ Пропущено (кулдаун): {skipped}")

    summary = "\n".join(lines)
    if len(summary) > 3900:
        summary = summary[:3900] + "\n\n…[обрезано]"

    # Заменяем progress-сообщение финальным
    try:
        await progress_msg.edit_text(summary)
    except Exception:
        # Если редактирование не удалось — пошлём новое
        await message.answer(summary)
