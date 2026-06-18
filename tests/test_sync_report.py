"""Тесты дружелюбного отчёта /sync (#138).

Классификатор исходов источника превращает технический вывод скрипта в один из
четырёх человекочитаемых исходов и НИКОГДА не показывает пользователю traceback,
Errno или внутренние пути.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from handlers import sync_cmd  # noqa: E402

# Подстроки, которые НИКОГДА не должны утечь в текст пользователю.
FORBIDDEN = ("Traceback", "Errno", "/app/", "PermissionError", "Exception", '  File "')


# --- Успех: OK vs NOOP --------------------------------------------------------


def test_success_with_new_data_is_ok():
    outcome, _ = sync_cmd._classify_success("Сохранено 5 новых записей")
    assert outcome == sync_cmd.OUTCOME_OK


def test_success_empty_output_is_ok():
    outcome, _ = sync_cmd._classify_success("")
    assert outcome == sync_cmd.OUTCOME_OK


def test_success_nothing_new_ru_is_noop():
    outcome, _ = sync_cmd._classify_success("Готово: новых данных нет")
    assert outcome == sync_cmd.OUTCOME_NOOP


def test_success_up_to_date_en_is_noop():
    outcome, _ = sync_cmd._classify_success("Weather data is up to date, 0 new entries")
    assert outcome == sync_cmd.OUTCOME_NOOP


# --- Провал: UNAVAILABLE vs ERROR --------------------------------------------


def test_network_failure_is_unavailable():
    outcome, detail = sync_cmd._classify_failure("garmin", "ConnectionError: Max retries exceeded with url")
    assert outcome == sync_cmd.OUTCOME_UNAVAILABLE
    assert not any(bad in detail for bad in FORBIDDEN)


def test_timeout_is_unavailable():
    outcome, _ = sync_cmd._classify_failure("garmin", "socket.timeout: timed out")
    assert outcome == sync_cmd.OUTCOME_UNAVAILABLE


def test_cgm_476_is_unavailable_and_mentions_abbott():
    dangerous = "476 Client Error: <none> for url: https://api-eu.libreview.io/llu/auth/login"
    outcome, detail = sync_cmd._classify_failure("glucose", dangerous)
    assert outcome == sync_cmd.OUTCOME_UNAVAILABLE
    assert "Abbott" in detail
    assert "<none>" not in detail  # опасный фрагмент не утёк


def test_permission_error_is_internal_error():
    raw = "PermissionError: [Errno 13] Permission denied: '/app/data/weather/weather_history.json'"
    outcome, detail = sync_cmd._classify_failure("weather", raw)
    assert outcome == sync_cmd.OUTCOME_ERROR
    assert not any(bad in detail for bad in FORBIDDEN)


def test_script_nonzero_marker_is_internal_error():
    outcome, detail = sync_cmd._classify_failure("workouts", "❌ parse_workouts.py вернул 1")
    assert outcome == sync_cmd.OUTCOME_ERROR
    assert "parse_workouts.py" not in detail


def test_no_traceback_leaks_for_any_known_failure():
    samples = [
        ("garmin", 'Traceback (most recent call last):\n  File "x.py", line 1\nModuleNotFoundError: no garth'),
        ("weather", "PermissionError: [Errno 13] Permission denied: '/app/data/weather/x.json'"),
        ("zepp", "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='api') Max retries"),
        ("glucose", "476 Client Error: <none> for url: https://api-eu.libreview.io/llu"),
    ]
    for src, raw in samples:
        _, detail = sync_cmd._classify_failure(src, raw)
        assert not any(bad in detail for bad in FORBIDDEN), f"утечка в {src}: {detail!r}"


def test_every_outcome_has_icon():
    for outcome in (
        sync_cmd.OUTCOME_OK,
        sync_cmd.OUTCOME_NOOP,
        sync_cmd.OUTCOME_UNAVAILABLE,
        sync_cmd.OUTCOME_ERROR,
    ):
        assert outcome in sync_cmd.OUTCOME_ICON


# --- Рендер отчёта ------------------------------------------------------------


def test_report_all_good_no_reassurance():
    results = [
        ("garmin", "Garmin (часы)", sync_cmd.OUTCOME_OK, "обновлено"),
        ("netatmo", "Netatmo (воздух дома)", sync_cmd.OUTCOME_NOOP, "актуально, новых данных нет"),
    ]
    text = sync_cmd._build_sync_report(results, "12с", [])
    assert text.startswith("✅")  # всё хорошо → зелёный заголовок
    assert "Готово: 1 обновлено, 1 актуально." in text
    assert "Данные не потеряны" not in text  # нечему теряться


def test_report_mixed_has_icons_and_reassurance():
    results = [
        ("garmin", "Garmin (часы)", sync_cmd.OUTCOME_OK, "обновлено"),
        ("glucose", "Глюкоза (CGM)", sync_cmd.OUTCOME_UNAVAILABLE, "сервис Abbott временно недоступен"),
        ("weather", "Погода (Open-Meteo)", sync_cmd.OUTCOME_ERROR, "не удалось обновить — записал в журнал"),
    ]
    text = sync_cmd._build_sync_report(results, "1м 3с", [])
    assert "⏳ Глюкоза —" in text
    assert "⚠️ Погода —" in text
    assert "✅ Garmin —" in text
    assert "1 обновлено" in text and "1 ждёт" in text and "1 с ошибкой" in text
    assert "Данные не потеряны." in text


def test_report_header_warns_on_error():
    results = [("weather", "Погода (Open-Meteo)", sync_cmd.OUTCOME_ERROR, "не удалось")]
    assert sync_cmd._build_sync_report(results, "2с", []).startswith("⚠️")


def test_report_header_waits_when_only_unavailable():
    results = [("glucose", "Глюкоза (CGM)", sync_cmd.OUTCOME_UNAVAILABLE, "сервис недоступен")]
    assert sync_cmd._build_sync_report(results, "2с", []).startswith("⏳")


def test_report_lists_cooldown_skips():
    results = [("garmin", "Garmin (часы)", sync_cmd.OUTCOME_OK, "обновлено")]
    text = sync_cmd._build_sync_report(results, "2с", [("zepp", 120)])
    assert "кулдаун" in text.lower()
    assert "Zepp" in text


def test_report_truncates_overlong():
    results = [("garmin", "Garmin (часы)", sync_cmd.OUTCOME_OK, "x" * 5000)]
    text = sync_cmd._build_sync_report(results, "2с", [])
    assert len(text) <= 3920
    assert "обрезано" in text
