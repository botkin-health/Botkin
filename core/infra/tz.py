"""Единая таймзона проекта.

MSK был скопирован `timezone(timedelta(hours=3))` в 9 модулях (аудит
11.06.2026) — теперь импортируется отсюда. Когда дойдём до настоящей
per-user таймзоны (в БД есть users.timezone) — менять в одном месте.
"""

from datetime import timedelta, timezone

MSK = timezone(timedelta(hours=3))
