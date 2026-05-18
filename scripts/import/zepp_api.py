#!/usr/bin/env python3
"""
Импорт данных Zepp Smart Scale (Mi Body Composition Scale 2) через API.

АРХИТЕКТУРА:
  Данные весов хранятся на cn3-сервере Zepp (Китай): api-mifit-cn3.zepp.com
  Этот сервер НЕ доступен из-за VPN (Россия/Европа) → запросы идут через
  Hetzner-сервер (116.203.213.137, Германия) как SSH-прокси.

АУТЕНТИФИКАЦИЯ:
  1. Xiaomi OAuth2 через браузер → получаем code
  2. Code обменивается на app_token через account.huami.com
  3. Токен кэшируется в data/cache/tokens.json (единое хранилище OAuth-токенов)
  4. Токен живёт ~5-7 дней, потом требуется повторная авторизация

Использование:
  # Обычный синк (токен из кэша, запрос через Hetzner):
  python3 scripts/import_zepp_api.py

  # Обновить токен (открой URL в браузере → скопируй redirect URL):
  python3 scripts/import_zepp_api.py --reauth

  # Принудительный полный бэкфил:
  python3 scripts/import_zepp_api.py --days 365

Выходной файл: data/zepp_export_latest.csv
"""

import requests
import json
import csv
import argparse
import subprocess
import sys
import os
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

_BASE = Path(__file__).resolve().parent.parent.parent  # HealthVault root
load_dotenv(_BASE / ".env")

BASE = Path(__file__).resolve().parent.parent.parent  # HealthVault root
TOKEN_CACHE = BASE / "data/cache/tokens.json"
CSV_OUT = BASE / "data/zepp_export_latest.csv"

# CN3 сервер Zepp (данные весов) — доступен только через Hetzner
ZEPP_CN3_API = "https://api-mifit-cn3.zepp.com"

# Hetzner proxy для доступа к CN3
HETZNER_HOST = "root@116.203.213.137"
HETZNER_PASS = "SERVER_PASSWORD_REDACTED"

# Xiaomi OAuth URL (для получения токена через браузер)
XIAOMI_OAUTH_URL = (
    "https://account.xiaomi.com/oauth2/authorize?"
    "skip_confirm=false&client_id=2882303761517383915&pt=0"
    "&scope=1+6000+16001+20000"
    "&redirect_uri=https%3A%2F%2Fhm.xiaomi.com%2Fwatch.do"
    "&_locale=en_US&response_type=code"
)

CACHE_KEY = "zepp/xiaomi:lyskovsky@gmail.com"

# Xiaomi account credentials (для auto-login без браузера)
ZEPP_EMAIL = os.environ.get("ZEPP_EMAIL", "")
ZEPP_PASSWORD = os.environ.get("ZEPP_PASSWORD", "")


def load_token() -> tuple[str, str]:
    """Load cached (user_id, app_token)."""
    if TOKEN_CACHE.exists():
        cache = json.loads(TOKEN_CACHE.read_text())
        val = cache.get(CACHE_KEY, "")
        if ":" in val:
            uid, tok = val.split(":", 1)
            return uid.strip(), tok.strip()
    raise FileNotFoundError("Токен не найден. Запусти: python3 scripts/import_zepp_api.py --reauth")


def save_token(user_id: str, app_token: str):
    """Save token to cache."""
    cache = {}
    if TOKEN_CACHE.exists():
        cache = json.loads(TOKEN_CACHE.read_text())
    cache[CACHE_KEY] = f"{user_id}:{app_token}"
    TOKEN_CACHE.write_text(json.dumps(cache, indent=2))


def exchange_code(code: str) -> tuple[str, str]:
    """Exchange OAuth code for app_token + user_id. Reusable by CLI and Claude."""
    r = requests.post(
        "https://account.huami.com/v2/client/login",
        data={
            "app_name": "com.xiaomi.hm.health",
            "app_version": "4.6.0",
            "code": code,
            "country_code": "US",
            "device_id": "02:00:00:00:00:00",
            "device_model": "iPhone14,2",
            "grant_type": "request_token",
            "third_name": "mi-watch",
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "MiFit/4.6.0 (iPhone; iOS 14.0.1; Scale/2)",
        },
        timeout=15,
    )

    data = r.json()
    if "token_info" not in data:
        raise Exception(f"Ошибка OAuth exchange: {json.dumps(data)[:200]}")

    ti = data["token_info"]
    user_id = str(ti["user_id"])
    app_token = ti["app_token"]

    save_token(user_id, app_token)
    print(f"   ✅ Токен получен! user_id={user_id}")
    return user_id, app_token


def do_reauth() -> tuple[str, str]:
    """Browser OAuth flow — открой URL, залогинься, вставь redirect."""
    print("\n   Открой эту ссылку в браузере и залогинься:\n")
    print(f"   {XIAOMI_OAUTH_URL}\n")
    print("   После логина скопируй URL из адресной строки (будет hm.xiaomi.com/watch.do?code=...)")

    redirect_url = input("\n   Вставь URL сюда: ").strip()

    # Extract code from URL
    if "code=" in redirect_url:
        code = redirect_url.split("code=")[1].split("&")[0]
    else:
        code = redirect_url  # Maybe they pasted just the code

    print(f"   Код: {code[:30]}...")

    # Exchange code for token
    r = requests.post(
        "https://account.huami.com/v2/client/login",
        data={
            "app_name": "com.xiaomi.hm.health",
            "app_version": "4.6.0",
            "code": code,
            "country_code": "US",
            "device_id": "02:00:00:00:00:00",
            "device_model": "iPhone14,2",
            "grant_type": "request_token",
            "third_name": "mi-watch",
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "MiFit/4.6.0 (iPhone; iOS 14.0.1; Scale/2)",
        },
        timeout=15,
    )

    data = r.json()
    if "token_info" not in data:
        raise Exception(f"Ошибка OAuth: {json.dumps(data)[:200]}")

    ti = data["token_info"]
    user_id = str(ti["user_id"])
    app_token = ti["app_token"]

    save_token(user_id, app_token)
    print(f"   ✅ Токен получен! user_id={user_id}")
    return user_id, app_token


def fetch_via_hetzner(user_id: str, app_token: str, start: str, end: str) -> list[dict]:
    """Fetch weight records from CN3.

    На сервере (env BOTKIN_DIRECT_API=1 либо мы внутри docker-контейнера) идём
    напрямую через requests — мы уже в Германии, CN3 доступен. На Mac (из
    VPN/России) — через SSH-прокси на Hetzner (старое поведение).
    """
    url = f"{ZEPP_CN3_API}/users/{user_id}/members/-1/weightRecords?from_date={start}&to_date={end}"
    headers = {"apptoken": app_token, "userid": user_id}

    if os.getenv("BOTKIN_DIRECT_API") == "1" or Path("/.dockerenv").exists():
        # Direct mode (на сервере / в контейнере)
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    else:
        # SSH proxy mode (с Mac)
        cmd = [
            "/opt/homebrew/bin/sshpass",
            "-p",
            HETZNER_PASS,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            HETZNER_HOST,
            f"curl -sS --max-time 30 -H 'apptoken: {app_token}' -H 'userid: {user_id}' '{url}'",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise Exception(f"SSH/curl error: {result.stderr[:200]}")
        data = json.loads(result.stdout)

    items = data.get("items", [])

    # Check for auth error (0108 = expired, 0102 = invalid token)
    inner_code = data.get("data", {}).get("code", "") if isinstance(data.get("data"), dict) else ""
    if not items and (data.get("code") == "0108" or inner_code in ("0102", "0108")):
        raise PermissionError("Токен устарел. Запусти: python3 scripts/import/zepp_api.py --reauth")

    return items


def items_to_csv_rows(items: list[dict]) -> list[dict]:
    """Convert API items to CSV format."""
    rows = []
    for item in items:
        s = item.get("summary", {})
        ts = item.get("generatedTime", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""

        rows.append(
            {
                "Date": dt,
                "Weight": s.get("weight", ""),
                "BMI": round(s.get("bmi", 0), 1) if s.get("bmi") else "",
                "BodyFat": s.get("fatRate", ""),
                "BodyWater": s.get("bodyWaterRate", ""),
                "BoneMass": s.get("boneMass", ""),
                "MetabolicAge": s.get("muscleAge", ""),
                "MuscleMass": s.get("muscleRate", ""),
                "PhysiqueRating": s.get("bodyScore", ""),
                "ProteinMass": s.get("proteinRatio", ""),
                "VisceralFat": s.get("visceralFat", ""),
                "BasalMetabolism": s.get("metabolism", ""),
                "HeartRate": s.get("heartRate", ""),
                "SkeletalMuscleMass": "",
                "User": "",
                "Source": item.get("deviceId", ""),
            }
        )
    return rows


def merge_and_save(new_rows: list[dict]) -> list[dict]:
    """Merge with existing CSV, deduplicate, save."""
    existing = []
    if CSV_OUT.exists():
        with open(CSV_OUT, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))

    by_key = {r["Date"][:16]: r for r in existing}
    for r in new_rows:
        by_key[r["Date"][:16]] = r
    all_rows = sorted(by_key.values(), key=lambda x: x["Date"])

    fieldnames = [
        "Date",
        "Weight",
        "BMI",
        "BodyFat",
        "BodyWater",
        "BoneMass",
        "MetabolicAge",
        "MuscleMass",
        "PhysiqueRating",
        "ProteinMass",
        "VisceralFat",
        "BasalMetabolism",
        "HeartRate",
        "SkeletalMuscleMass",
        "User",
        "Source",
    ]
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Zepp Smart Scale API import")
    parser.add_argument("--reauth", action="store_true", help="Обновить токен через браузер OAuth")
    parser.add_argument("--code", type=str, help="OAuth code напрямую (без interactive input)")
    parser.add_argument("--days", type=int, default=30, help="Дней истории (default: 30)")
    args = parser.parse_args()

    print("⚖️  Zepp Smart Scale — импорт через API (CN3 → Hetzner proxy)...")

    try:
        if args.code:
            # Claude или скрипт передал code напрямую
            code = args.code
            if "code=" in code:
                code = code.split("code=")[1].split("&")[0]
            user_id, app_token = exchange_code(code)
        elif args.reauth:
            user_id, app_token = do_reauth()
        else:
            try:
                user_id, app_token = load_token()
            except FileNotFoundError:
                print("   ⚠️  Токен не найден")
                print(f"   Нужна авторизация. Открой:\n   {XIAOMI_OAUTH_URL}")
                print("   Затем запусти: python3 scripts/import/zepp_api.py --code 'REDIRECT_URL'")
                return

        print(f"   Аккаунт: user_id={user_id}")

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

        try:
            items = fetch_via_hetzner(user_id, app_token, start, end)
        except PermissionError:
            print("   ⚠️  Токен устарел!")
            print(f"   Нужна авторизация. Открой:\n   {XIAOMI_OAUTH_URL}")
            print("   Затем запусти: python3 scripts/import/zepp_api.py --code 'REDIRECT_URL'")
            return

        print(f"   Получено {len(items)} записей от CN3 API")

        if not items:
            print("   ⚠️  Нет новых записей")
            return

        new_rows = items_to_csv_rows(items)
        all_rows = merge_and_save(new_rows)

        recent = [r for r in all_rows if r["Date"] >= "2026-03-01"]
        print(f"   ✅ CSV обновлён: {len(all_rows)} записей всего, {len(recent)} в марте")
        if recent:
            last = recent[-1]
            print(
                f"   Последняя: {last['Date']} — {last['Weight']}кг, жир {last['BodyFat']}%, висцер {last['VisceralFat']}"
            )

    except Exception as e:
        print(f"   ❌ Ошибка: {e}")


if __name__ == "__main__":
    main()
