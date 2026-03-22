#!/usr/bin/env python3
"""
Импорт истории браузера Chrome → HealthVault.

Что собираем (по мотивам биохакеров, использующих RescueTime):
  - Визиты по доменам с категориями (соцсети / работа / развлечения / ИИ / ...)
  - Почасовое распределение активности (когда реально работаю, когда отвлекаюсь)
  - Предсонная зона: активность за 2 часа до полуночи
  - Переключения контекста: смены домена/категории в час (мера расфокуса)
  - Сводка по категориям: сколько минут на соцсети vs продуктивность

Выходной файл: data/activities/chrome_history.json
Формат:
  {
    "2026-03-09": {
      "total_visits": 229,
      "domains": [
        {"domain": "claude.ai", "category": "ai_tools", "visits": 15, "minutes_est": 45.2},
        ...
      ],
      "categories": {
        "ai_tools":          {"visits": 20, "minutes_est": 60.0},
        "social_media":      {"visits": 40, "minutes_est": 30.0},
        ...
      },
      "hourly": {
        "09": {"visits": 12, "top_domain": "gmail.com", "top_category": "communication"},
        ...
      },
      "pre_sleep_2h": {               // последние 2 часа перед 00:00
        "total_visits": 25,
        "categories": {"entertainment": 15, "social_media": 8}
      },
      "context_switches_per_hour": 4.2   // средн. смен домена/час (расфокус)
    }
  }
"""

import sqlite3
import shutil
import os
import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import urlparse

CHROME_HISTORY_PATH = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome/Default/History"
)
TMP_DB = "/tmp/chrome_history_hv.db"

# Московское время UTC+3
UTC_OFFSET = timedelta(hours=3)

OUTPUT_FILE = "data/activities/chrome_history.json"

# ─── Категории доменов ────────────────────────────────────────────────────────
# Порядок важен: первое совпадение побеждает

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("ai_tools", [
        "claude.ai", "chat.openai.com", "chatgpt.com", "perplexity.ai",
        "gemini.google.com", "copilot.microsoft.com", "you.com",
        "phind.com", "poe.com", "character.ai",
    ]),
    ("social_media", [
        "twitter.com", "x.com", "facebook.com", "instagram.com",
        "vk.com", "reddit.com", "tiktok.com", "linkedin.com",
        "threads.net", "pikabu.ru",
    ]),
    ("entertainment", [
        "youtube.com", "youtu.be", "netflix.com", "twitch.tv",
        "kinopoisk.ru", "ivi.ru", "okko.tv", "more.tv",
        "spotify.com", "music.yandex.ru", "music.apple.com",
        "rutube.ru",
    ]),
    ("news_media", [
        "meduza.io", "rbc.ru", "vc.ru", "habr.com", "tjournal.ru",
        "republic.ru", "novayagazeta.ru", "kommersant.ru",
        "the-village.ru", "wonderzine.com", "snob.ru",
        "echo.msk.ru", "lenta.ru",
    ]),
    ("work_productivity", [
        "docs.google.com", "sheets.google.com", "slides.google.com",
        "drive.google.com", "notion.so", "github.com", "gitlab.com",
        "figma.com", "miro.com", "trello.com", "asana.com",
        "airtable.com", "linear.app", "clickup.com",
        "jira.", "confluence.", "bitrix24.",
    ]),
    ("communication", [
        "gmail.com", "mail.google.com", "mail.yandex.ru",
        "web.telegram.org", "web.whatsapp.com",
        "slack.com", "discord.com", "teams.microsoft.com",
        "zoom.us", "us06web.zoom.us", "meet.google.com",
        "telemost.yandex.ru", "telemost.yandex.by",
        "spark.readdle.com", "calendar.google.com",
    ]),
    ("finance_crypto", [
        "binance.com", "coinbase.com", "bybit.com", "okx.com",
        "tradingview.com", "investing.com", "moex.com",
        "tinkoff.ru", "sberbank.ru", "alfabank.ru",
        "cbrf.ru",
    ]),
    ("health_biohacking", [
        "garmin.com", "connect.garmin.com", "whoop.com",
        "welltory.com", "cronometer.com", "examine.com",
        "pubmed.ncbi.nlm.nih.gov", "scholar.google.com",
        "oura.com",
    ]),
    ("shopping", [
        "ozon.ru", "wildberries.ru", "market.yandex.ru",
        "lamoda.ru", "avito.ru", "amazon.com", "aliexpress.com",
        "lavka.yandex.ru", "sbermegamarket.ru",
    ]),
    ("maps_travel", [
        "maps.google.com", "yandex.ru/maps", "2gis.ru",
        "booking.com", "airbnb.com", "aviasales.ru",
        "trip.com",
    ]),
    ("dev_tools", [
        "stackoverflow.com", "developer.apple.com", "developer.android.com",
        "npmjs.com", "pypi.org", "hub.docker.com",
        "localhost", "127.0.0.1",
    ]),
]

OTHER_CATEGORY = "other"


def categorize(domain: str) -> str:
    d = domain.lower().lstrip("www.")
    for category, patterns in CATEGORY_RULES:
        for p in patterns:
            if p in d:
                return category
    return OTHER_CATEGORY


def extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        # Убираем www. и порт
        host = re.sub(r"^www\.", "", host)
        host = re.sub(r":\d+$", "", host)
        return host.lower() if host else url[:50]
    except Exception:
        return url[:50]


def read_chrome_history() -> list[dict]:
    """Читаем Chrome History DB (копируем чтобы не блокировать Chrome)."""
    if not os.path.exists(CHROME_HISTORY_PATH):
        print(f"❌ Chrome History не найдена: {CHROME_HISTORY_PATH}")
        return []

    try:
        shutil.copy2(CHROME_HISTORY_PATH, TMP_DB)
    except Exception as e:
        print(f"❌ Не могу скопировать Chrome History: {e}")
        return []

    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Chrome хранит время в microseconds с 1601-01-01 (Windows FILETIME epoch)
    # Смещение от Unix epoch: 11644473600 секунд
    CHROME_EPOCH_OFFSET = 11_644_473_600

    cur.execute("""
        SELECT
            v.visit_time,
            v.visit_duration,
            u.url,
            u.title
        FROM visits v
        JOIN urls u ON v.url = u.id
        WHERE v.visit_time > 0
          AND u.url NOT LIKE 'chrome://%'
          AND u.url NOT LIKE 'chrome-extension://%'
          AND u.url NOT LIKE 'about:%'
        ORDER BY v.visit_time ASC
    """)

    rows = cur.fetchall()
    conn.close()
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)

    visits = []
    for r in rows:
        visit_time_sec = r["visit_time"] / 1_000_000 - CHROME_EPOCH_OFFSET
        dt_utc = datetime.utcfromtimestamp(visit_time_sec).replace(tzinfo=None)
        dt_local = dt_utc + UTC_OFFSET
        visit_dur_sec = (r["visit_duration"] or 0) / 1_000_000

        visits.append({
            "dt": dt_local,
            "url": r["url"],
            "title": r["title"] or "",
            "domain": extract_domain(r["url"]),
            "visit_duration_sec": visit_dur_sec,
        })

    return visits


def estimate_time_spent(visits: list[dict]) -> list[dict]:
    """
    Оцениваем время на странице через интервал между визитами.
    Chrome's visit_duration часто = 0 для коротких визитов.
    Алгоритм: время_на_странице = min(следующий_визит - текущий, 5 мин)
    Если следующий визит > 5 мин — считаем 1 мин (пользователь ушёл).
    """
    MAX_GAP = 5 * 60  # 5 минут максимум на страницу
    DEFAULT_LAST = 60  # последний визит в сессии = 1 мин

    enriched = []
    for i, v in enumerate(visits):
        # Если Chrome дал duration — используем его (если > 0)
        if v["visit_duration_sec"] > 0:
            est_sec = min(v["visit_duration_sec"], MAX_GAP)
        elif i < len(visits) - 1:
            gap = (visits[i + 1]["dt"] - v["dt"]).total_seconds()
            est_sec = min(gap, MAX_GAP) if gap > 0 else DEFAULT_LAST
        else:
            est_sec = DEFAULT_LAST

        enriched.append({**v, "est_sec": est_sec})

    return enriched


def build_daily(visits: list[dict]) -> dict:
    """Агрегируем визиты по дням."""
    # Группируем по дате
    by_day: dict[str, list[dict]] = defaultdict(list)
    for v in visits:
        date_str = v["dt"].strftime("%Y-%m-%d")
        by_day[date_str].append(v)

    result = {}
    for date_str in sorted(by_day.keys()):
        day_visits = by_day[date_str]
        result[date_str] = build_day(day_visits)

    return result


def build_day(visits: list[dict]) -> dict:
    """Строим аналитику за один день."""

    # ── Агрегация по доменам ─────────────────────────────────────────────────
    domain_stats: dict[str, dict] = defaultdict(lambda: {"visits": 0, "est_sec": 0.0, "category": ""})
    for v in visits:
        d = v["domain"]
        domain_stats[d]["visits"] += 1
        domain_stats[d]["est_sec"] += v["est_sec"]
        domain_stats[d]["category"] = categorize(d)

    domains_sorted = sorted(domain_stats.items(), key=lambda x: x[1]["est_sec"], reverse=True)
    domains_list = [
        {
            "domain": d,
            "category": info["category"],
            "visits": info["visits"],
            "minutes_est": round(info["est_sec"] / 60, 1),
        }
        for d, info in domains_sorted
        if info["visits"] > 0
    ]

    # ── Категории ────────────────────────────────────────────────────────────
    cat_stats: dict[str, dict] = defaultdict(lambda: {"visits": 0, "est_sec": 0.0})
    for v in visits:
        cat = categorize(v["domain"])
        cat_stats[cat]["visits"] += 1
        cat_stats[cat]["est_sec"] += v["est_sec"]

    categories = {
        cat: {"visits": info["visits"], "minutes_est": round(info["est_sec"] / 60, 1)}
        for cat, info in sorted(cat_stats.items(), key=lambda x: x[1]["est_sec"], reverse=True)
    }

    # ── Почасовая активность ──────────────────────────────────────────────────
    hourly: dict[str, dict] = defaultdict(lambda: {"visits": 0, "est_sec": 0.0, "domains": defaultdict(float)})
    for v in visits:
        h = v["dt"].strftime("%H")
        hourly[h]["visits"] += 1
        hourly[h]["est_sec"] += v["est_sec"]
        hourly[h]["domains"][v["domain"]] += v["est_sec"]

    hourly_out = {}
    for h in sorted(hourly.keys()):
        hdata = hourly[h]
        top_d = max(hdata["domains"].items(), key=lambda x: x[1]) if hdata["domains"] else ("", 0)
        hourly_out[h] = {
            "visits": hdata["visits"],
            "minutes_est": round(hdata["est_sec"] / 60, 1),
            "top_domain": top_d[0],
            "top_category": categorize(top_d[0]),
        }

    # ── Предсонная зона: 22:00–00:00 ─────────────────────────────────────────
    pre_sleep = [v for v in visits if v["dt"].hour >= 22]
    ps_cat: dict[str, int] = defaultdict(int)
    for v in pre_sleep:
        ps_cat[categorize(v["domain"])] += 1

    pre_sleep_out = {
        "total_visits": len(pre_sleep),
        "categories": dict(sorted(ps_cat.items(), key=lambda x: x[1], reverse=True)),
    }

    # ── Переключения контекста ────────────────────────────────────────────────
    # Считаем смены домена в час (мера расфокуса)
    if len(visits) > 1:
        total_hours = max(
            (visits[-1]["dt"] - visits[0]["dt"]).total_seconds() / 3600, 1
        )
        # Смена домена = когда следующий домен ≠ текущему
        switches = sum(
            1 for i in range(1, len(visits))
            if visits[i]["domain"] != visits[i - 1]["domain"]
        )
        ctx_switches_per_hour = round(switches / total_hours, 1)
    else:
        ctx_switches_per_hour = 0.0

    return {
        "total_visits": len(visits),
        "domains": domains_list,
        "categories": categories,
        "hourly": hourly_out,
        "pre_sleep_22_00": pre_sleep_out,
        "context_switches_per_hour": ctx_switches_per_hour,
    }


def fmt_time(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м"


CATEGORY_ICONS = {
    "ai_tools": "🤖",
    "social_media": "📱",
    "entertainment": "🎬",
    "news_media": "📰",
    "work_productivity": "💼",
    "communication": "✉️",
    "finance_crypto": "💰",
    "health_biohacking": "🏃",
    "shopping": "🛒",
    "maps_travel": "🗺️",
    "dev_tools": "💻",
    "other": "🌐",
}


def main():
    print("🌐 Импорт Chrome History → HealthVault...")
    print(f"   Читаю: {CHROME_HISTORY_PATH}")

    visits_raw = read_chrome_history()
    if not visits_raw:
        exit(1)

    print(f"   Всего визитов в истории: {len(visits_raw):,}")

    visits = estimate_time_spent(visits_raw)
    output = build_daily(visits)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    dates = sorted(output.keys())
    print(f"\n✅ Сохранено {len(dates)} дней → {OUTPUT_FILE}")
    print(f"📅 Период: {dates[0]} — {dates[-1]}")
    print()

    # Последние 7 дней
    print("📊 Последние 7 дней:")
    for date_str in dates[-7:]:
        day = output[date_str]
        cats = day["categories"]
        social = cats.get("social_media", {}).get("minutes_est", 0)
        entertain = cats.get("entertainment", {}).get("minutes_est", 0)
        work = cats.get("work_productivity", {}).get("minutes_est", 0)
        ai = cats.get("ai_tools", {}).get("minutes_est", 0)
        pre_sleep_v = day["pre_sleep_22_00"]["total_visits"]
        ctx = day["context_switches_per_hour"]
        print(f"   {date_str}: {day['total_visits']} визитов | "
              f"💼{fmt_time(work)} 🤖{fmt_time(ai)} 📱{fmt_time(social)} 🎬{fmt_time(entertain)} | "
              f"🌙pre-sleep:{pre_sleep_v}v | 🔀{ctx}sw/h")

    print()

    # Сегодня детально
    today = dates[-1]
    day = output[today]
    print(f"🔍 Детали за {today}:")
    print(f"   Переключения контекста: {day['context_switches_per_hour']} смен/час")
    print(f"   Перед сном (22-00): {day['pre_sleep_22_00']['total_visits']} визитов")
    if day["pre_sleep_22_00"]["categories"]:
        for cat, cnt in list(day["pre_sleep_22_00"]["categories"].items())[:5]:
            icon = CATEGORY_ICONS.get(cat, "🌐")
            print(f"     {icon} {cat}: {cnt}")

    print()
    print("   Категории за день:")
    for cat, info in day["categories"].items():
        icon = CATEGORY_ICONS.get(cat, "🌐")
        print(f"     {icon} {cat:25s} {fmt_time(info['minutes_est']):>8}  ({info['visits']} визитов)")

    print()
    print("   Топ-10 доменов:")
    for d in day["domains"][:10]:
        icon = CATEGORY_ICONS.get(d["category"], "🌐")
        print(f"     {icon} {d['domain']:35s} {fmt_time(d['minutes_est']):>8}  ({d['visits']}v)")

    print()
    print("   Почасовая активность:")
    for h in sorted(day["hourly"].keys()):
        hdata = day["hourly"][h]
        bar = "█" * min(int(hdata["visits"] / 3), 30)
        icon = CATEGORY_ICONS.get(hdata["top_category"], "🌐")
        print(f"     {h}:00  {bar:<30} {hdata['visits']:>3}v  {icon}{hdata['top_domain']}")


if __name__ == "__main__":
    main()
