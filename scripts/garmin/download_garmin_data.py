#!/opt/homebrew/bin/python3.13
"""
Скрипт для загрузки данных из Garmin Connect
Загружает все доступные данные за указанный период.

Использует garth для хранения OAuth-сессии (~1 год без повторного логина).
При HTTP 429 (rate limit) — exponential backoff с паузой до 10 минут.
Между запросами — пауза 1 сек для предотвращения rate limiting.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv(Path(__file__).parent.parent.parent / ".env")

try:
    from garminconnect import Garmin
    import garth
except ImportError:
    print("❌ Библиотека garminconnect не установлена")
    print("Установите: pip install garminconnect garth python-dotenv")
    sys.exit(1)

# Настройки
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "garmin"
GARTH_HOME = BASE_DIR / "data" / "cache" / "garth_tokens"
EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")

# Rate limiting
REQUEST_DELAY = 1.0  # секунд между запросами
MAX_RETRIES = 3  # максимум попыток при 429
BACKOFF_BASE = 300  # 5 минут базовая пауза при 429


def ensure_dirs():
    """Создает необходимые директории"""
    for subdir in ["activities", "daily-summary", "sleep", "metrics", "body-battery", "stress", "hrv"]:
        (DATA_DIR / subdir).mkdir(parents=True, exist_ok=True)
    GARTH_HOME.mkdir(parents=True, exist_ok=True)


def save_json(data, filepath):
    """Сохраняет данные в JSON файл"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def api_call(func, *args, **kwargs):
    """Обёртка для API-вызовов с retry при 429 и паузой между запросами."""
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            return func(*args, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "too many requests" in err_str:
                wait = BACKOFF_BASE * (attempt + 1)
                print(f"   ⏳ Rate limit (429), жду {wait // 60} мин... (попытка {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                raise
    raise Exception(f"Garmin API: {MAX_RETRIES} попыток исчерпано (429)")


def login_garmin():
    """Логин через garth с кэшированной сессией (~1 год)."""
    token_dir = str(GARTH_HOME)

    # Попробуем загрузить сохранённую сессию
    try:
        garth.resume(token_dir)
        client = Garmin()
        client.login(token_dir)
        print("✅ Garmin: загружена сохранённая сессия (garth)")
        return client
    except Exception:
        pass

    # Свежий логин с retry при 429
    if not EMAIL or not PASSWORD:
        print("❌ Ошибка: GARMIN_EMAIL и GARMIN_PASSWORD должны быть в .env файле")
        sys.exit(1)

    print("🔐 Garmin: логин...")
    try:
        client = Garmin(EMAIL, PASSWORD)
        client.login()
        client.garth.dump(token_dir)
        print("✅ Garmin: логин успешен, сессия сохранена в", token_dir)
        return client
    except Exception as e:
        if "429" in str(e):
            print("❌ Garmin: rate limit (429) — IP заблокирован Garmin, нужно подождать ~24 часа.")
            print("   Данные Garmin остались на прежней дате. Остальные источники продолжат работу.")
        else:
            print(f"❌ Garmin: ошибка входа — {type(e).__name__}: {e}")
        sys.exit(1)


def download_activities(client, start_date, end_date):
    """Загружает все активности за период"""
    print(f"\n📥 Загрузка активностей с {start_date} по {end_date}...")
    activities_dir = DATA_DIR / "activities"

    try:
        activities = api_call(client.get_activities_by_date, start_date, end_date)
        print(f"   Найдено активностей: {len(activities)}")

        for activity in activities:
            activity_id = activity.get("activityId")
            if not activity_id:
                continue

            # Сохраняем краткую информацию
            # Нормализуем дату: startTimeLocal может быть "2026-03-09 19:07:41" или "2026-03-09T19:07:41"
            start_raw = activity.get("startTimeLocal", "")
            date_str = start_raw[:10] if start_raw else "unknown"
            time_str = start_raw[11:16].replace(":", "") if len(start_raw) > 10 else "0000"
            filename = f"{date_str}_{time_str}_{activity_id}.json"
            save_json(activity, activities_dir / filename)
            print(
                f"   ✅ {activity.get('activityName', 'Activity')} ({activity.get('activityType', {}).get('typeKey', '?')}) - {date_str} {start_raw[11:16]}"
            )

        return len(activities)
    except Exception as e:
        print(f"   ❌ Ошибка загрузки активностей: {e}")
        return 0


def download_daily_summary(client, start_date, end_date):
    """Загружает дневные сводки (шаги, калории, статистика)"""
    print(f"\n📥 Загрузка дневных сводок с {start_date} по {end_date}...")
    summary_dir = DATA_DIR / "daily-summary"

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    count = 0

    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        filename = f"{date_str}.json"
        filepath = summary_dir / filename

        # Пропускаем если уже загружено, НО если это сегодня - обновляем
        today_str = datetime.now().strftime("%Y-%m-%d")
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue

        try:
            # Собираем данные из разных источников
            summary = {}

            # Статистика за день
            try:
                stats = api_call(client.get_stats, date_str)
                summary["stats"] = stats
            except:
                pass

            # Шаги
            try:
                steps = api_call(client.get_steps_data, date_str)
                summary["steps"] = steps
            except:
                pass

            # Дневные шаги (альтернативный метод)
            try:
                daily_steps = api_call(client.get_daily_steps, date_str)
                summary["daily_steps"] = daily_steps
            except:
                pass

            if summary:
                save_json(summary, filepath)
                count += 1
                print(f"   ✅ {date_str}")
            else:
                print(f"   ⚠️  {date_str}: нет данных")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")

        current_date += timedelta(days=1)

    return count


def download_sleep(client, start_date, end_date):
    """Загружает данные о сне"""
    print(f"\n📥 Загрузка данных о сне с {start_date} по {end_date}...")
    sleep_dir = DATA_DIR / "sleep"

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    count = 0

    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        filename = f"{date_str}.json"
        filepath = sleep_dir / filename

        today_str = datetime.now().strftime("%Y-%m-%d")
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue

        try:
            sleep_data = api_call(client.get_sleep_data, date_str)
            save_json(sleep_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")

        current_date += timedelta(days=1)

    return count


def download_body_battery(client, start_date, end_date):
    """Загружает данные Body Battery"""
    print(f"\n📥 Загрузка Body Battery с {start_date} по {end_date}...")
    bb_dir = DATA_DIR / "body-battery"

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    count = 0

    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        filename = f"{date_str}.json"
        filepath = bb_dir / filename

        today_str = datetime.now().strftime("%Y-%m-%d")
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue

        try:
            bb_data = api_call(client.get_body_battery, date_str)
            save_json(bb_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")

        current_date += timedelta(days=1)

    return count


def download_stress(client, start_date, end_date):
    """Загружает данные о стрессе"""
    print(f"\n📥 Загрузка данных о стрессе с {start_date} по {end_date}...")
    stress_dir = DATA_DIR / "stress"

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    count = 0

    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        filename = f"{date_str}.json"
        filepath = stress_dir / filename

        today_str = datetime.now().strftime("%Y-%m-%d")
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue

        try:
            stress_data = api_call(client.get_stress_data, date_str)
            save_json(stress_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")

        current_date += timedelta(days=1)

    return count


def download_hrv(client, start_date, end_date):
    """Загружает данные HRV"""
    print(f"\n📥 Загрузка HRV данных с {start_date} по {end_date}...")
    hrv_dir = DATA_DIR / "hrv"

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    count = 0

    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        filename = f"{date_str}.json"
        filepath = hrv_dir / filename

        today_str = datetime.now().strftime("%Y-%m-%d")
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue

        try:
            hrv_data = api_call(client.get_hrv_data, date_str)
            save_json(hrv_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")

        current_date += timedelta(days=1)

    return count


def main():
    ensure_dirs()
    client = login_garmin()

    # Получаем информацию о пользователе
    try:
        user_profile = api_call(client.get_user_profile)
        print(f"👤 Пользователь: {user_profile.get('displayName', 'Unknown')}")
    except:
        pass

    # Определяем период (последний год)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    print(f"\n📅 Период загрузки: {start_date} - {end_date}")

    # Загружаем данные
    results = {
        "activities": download_activities(client, start_date, end_date),
        "daily_summary": download_daily_summary(client, start_date, end_date),
        "sleep": download_sleep(client, start_date, end_date),
        "body_battery": download_body_battery(client, start_date, end_date),
        "stress": download_stress(client, start_date, end_date),
        "hrv": download_hrv(client, start_date, end_date),
    }

    # Сохраняем метаданные о загрузке
    metadata = {
        "download_date": datetime.now().isoformat(),
        "period": {"start": start_date, "end": end_date},
        "results": results,
    }
    save_json(metadata, DATA_DIR / "download_metadata.json")

    print(f"\n{'=' * 60}")
    print("✅ ЗАГРУЗКА ЗАВЕРШЕНА")
    print(f"{'=' * 60}")
    print(f"Активности: {results['activities']}")
    print(f"Дневные сводки: {results['daily_summary']}")
    print(f"Сон: {results['sleep']}")
    print(f"Body Battery: {results['body_battery']}")
    print(f"Stress: {results['stress']}")
    print(f"HRV: {results['hrv']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
