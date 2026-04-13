#!/usr/bin/env python3
"""График клетчатки по дням с нормой."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, date, timedelta
import statistics
import os

raw = [
    ("2026-01-28", 381.5),
    ("2026-01-29", 25.2),
    ("2026-01-31", 9.3),
    ("2026-02-01", 7.8),
    ("2026-02-04", 24.3),
    ("2026-02-05", 12.2),
    ("2026-02-06", 8.8),
    ("2026-02-07", 6.9),
    ("2026-02-08", 2.1),
    ("2026-02-09", 11.7),
    ("2026-02-10", 25.6),
    ("2026-02-11", 15.0),
    ("2026-02-12", 4.5),
    ("2026-02-13", 14.6),
    ("2026-02-14", 12.8),
    ("2026-02-15", 33.5),
    ("2026-02-16", 29.8),
    ("2026-02-17", 9.1),
    ("2026-02-18", 22.7),
    ("2026-02-19", 13.3),
    ("2026-02-20", 20.9),
    ("2026-02-21", 17.8),
    ("2026-02-22", 32.3),
    ("2026-02-23", 25.0),
    ("2026-02-24", 8.1),
    ("2026-02-25", 14.5),
    ("2026-02-26", 28.0),
    ("2026-02-27", 2.2),
    ("2026-02-28", 33.5),
    ("2026-03-01", 16.6),
    ("2026-03-02", 15.0),
    ("2026-03-03", 11.5),
    ("2026-03-04", 27.7),
    ("2026-03-05", 33.5),
    ("2026-03-06", 16.5),
    ("2026-03-07", 27.1),
    ("2026-03-08", 18.2),
    ("2026-03-09", 31.0),
    ("2026-03-10", 10.4),
    ("2026-03-11", 26.8),
    ("2026-03-12", 18.8),
    ("2026-03-13", 18.4),
    ("2026-03-14", 10.8),
    ("2026-03-15", 3.5),
    ("2026-03-16", 16.5),
    ("2026-03-17", 16.6),
    ("2026-03-18", 23.2),
    ("2026-03-19", 11.5),
    ("2026-03-20", 10.9),
    ("2026-03-21", 15.0),
    ("2026-03-22", 23.8),
    ("2026-03-23", 16.0),
    ("2026-03-24", 14.5),
    ("2026-03-25", 25.1),
    ("2026-03-26", 12.7),
    ("2026-03-27", 6.3),
    ("2026-03-28", 14.7),
    ("2026-03-29", 3.0),
    ("2026-03-30", 25.4),
    ("2026-03-31", 21.8),
    ("2026-04-01", 9.1),
    ("2026-04-02", 25.5),
]

NORM = 30
# 2026-01-28 — артефакт миграции (97 записей из всей истории слиты в одну дату)
SKIP_DATES = {"2026-01-28"}

dates, values = [], []
for d_str, v in raw:
    if d_str in SKIP_DATES:
        continue
    d = datetime.strptime(d_str, "%Y-%m-%d").date()
    dates.append(d)
    values.append(v)

paired = sorted(zip(dates, values))
sdates = [x[0] for x in paired]
svals = [x[1] for x in paired]

# 7-дневное скользящее среднее
avg7 = []
for i in range(len(sdates)):
    w = [svals[j] for j in range(max(0, i - 3), min(len(svals), i + 4))]
    avg7.append(statistics.mean(w))

mean_val = statistics.mean(svals)
days_above = sum(1 for v in svals if v >= NORM)
pct = days_above / len(svals) * 100

# Цвета баров
colors = ["#4caf50" if v >= NORM else "#e67e22" for v in svals]

fig, ax = plt.subplots(figsize=(14, 6))
fig.patch.set_facecolor("#0f1117")
ax.set_facecolor("#1a1d2e")

ax.bar(sdates, svals, color=colors, alpha=0.85, width=0.8, zorder=2)

# Норма
ax.axhline(NORM, color="#2196f3", linewidth=1.8, linestyle="--", label=f"Норма {NORM}г/день", zorder=3)

# 7-дн. среднее
ax.plot(sdates, avg7, color="#ce93d8", linewidth=2.2, label="7-дн. среднее", zorder=4)

# Среднее за всё время
ax.axhline(mean_val, color="#ffd54f", linewidth=1, linestyle=":", alpha=0.7, label=f"Среднее {mean_val:.1f}г", zorder=3)

# Зона нормы (фон)
ax.fill_between([sdates[0] - timedelta(days=1), date(2026, 4, 3)], NORM, 80, color="#2196f3", alpha=0.04)


ax.set_ylim(0, 45)
ax.set_xlim(date(2026, 1, 28), date(2026, 4, 4))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)

ax.set_ylabel("Клетчатка, г/день", color="#cccccc", fontsize=11)
ax.tick_params(colors="#aaaaaa")
ax.spines[:].set_visible(False)
ax.yaxis.grid(True, color="#2a2d3e", linewidth=0.5, zorder=0)

title = f"Клетчатка по дням  |  среднее {mean_val:.1f}г  |  норма выполнена {days_above}/{len(svals)} дней ({pct:.0f}%)"
ax.set_title(title, color="white", fontsize=12, pad=12)
ax.legend(loc="upper right", framealpha=0.25, labelcolor="white", fontsize=9)

plt.tight_layout()
out = os.path.expanduser(f"~/Downloads/HealthVault_fiber_{date.today()}.png")
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"OK: {out}")
