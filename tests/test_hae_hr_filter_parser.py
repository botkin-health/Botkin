"""Проводка фильтра артефактов в HAE v2 парсере (_hae_to_daily_payloads).

Чисто in-memory, без БД. Проверяет что heart_rate Min из HAE проходит через
classify_hr_min: мусор <30 не попадает в payload, пограничные 30-39 помечаются.
"""

import sys
from pathlib import Path

# webhook.* лежит в telegram-bot/ (дефис → не пакетное имя, добавляем в путь)
TG_BOT = Path(__file__).resolve().parent.parent / "telegram-bot"
if str(TG_BOT) not in sys.path:
    sys.path.insert(0, str(TG_BOT))

from webhook.apple_health import _hae_to_daily_payloads


def _hr_metric(date_str, min_val, avg=60, max_val=120):
    return [
        {
            "name": "heart_rate",
            "units": "count/min",
            "data": [{"date": f"{date_str} 00:00:00 +0000", "Min": min_val, "Avg": avg, "Max": max_val}],
        }
    ]


def test_artifact_min_dropped_from_payload():
    daily = _hae_to_daily_payloads(_hr_metric("2026-06-09", min_val=13))
    p = daily["2026-06-09"]
    assert p.heart_rate_min is None  # мусор off-wrist — отброшен
    assert p.heart_rate_avg == 60  # avg/max не трогаем
    assert p.heart_rate_max == 120


def test_borderline_min_kept_and_flagged():
    daily = _hae_to_daily_payloads(_hr_metric("2026-06-09", min_val=35))
    p = daily["2026-06-09"]
    assert p.heart_rate_min == 35
    assert p.heart_rate_min_verify is True


def test_real_bradycardia_kept_unflagged():
    daily = _hae_to_daily_payloads(_hr_metric("2026-06-09", min_val=46))
    p = daily["2026-06-09"]
    assert p.heart_rate_min == 46
    assert p.heart_rate_min_verify in (None, False)
