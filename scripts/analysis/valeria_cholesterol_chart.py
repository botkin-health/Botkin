"""График холестерина и липидов мамы (Валерия Лысковская) за 10 лет."""

import json
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

KB_PATH = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault/Валерия Лысковская — Здоровье/knowledge_base.json"
)
OUT_PATH = Path(__file__).resolve().parent / "valeria_cholesterol.png"

kb = json.loads(KB_PATH.read_text(encoding="utf-8"))

points = []
for t in kb["blood_tests"]:
    d = datetime.fromisoformat(t["date"])
    v = t["values"]
    points.append(
        {
            "date": d,
            "chol": v.get("cholesterol"),
            "ldl": v.get("LDL"),
            "hdl": v.get("HDL"),
            "tg": v.get("triglycerides"),
        }
    )
points.sort(key=lambda p: p["date"])


def series(key):
    return (
        [p["date"] for p in points if p[key] is not None],
        [p[key] for p in points if p[key] is not None],
    )


# размеры — крупно для пожилого читателя
plt.rcParams.update(
    {
        "font.size": 14,
        "axes.titlesize": 18,
        "axes.labelsize": 15,
        "legend.fontsize": 13,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
    }
)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 12), sharex=True, gridspec_kw={"height_ratios": [2.3, 1]})

# --- верхняя панель ---
chol_x, chol_y = series("chol")
ldl_x, ldl_y = series("ldl")

ax1.plot(chol_x, chol_y, "o-", color="#c0392b", lw=2.8, markersize=10, label="Общий холестерин", zorder=5)
ax1.plot(ldl_x, ldl_y, "s-", color="#e67e22", lw=2.4, markersize=9, label="ЛПНП («плохой»)", zorder=4)

# зоны риска
ax1.axhspan(0, 5.0, color="#27ae60", alpha=0.09, zorder=1)
ax1.axhspan(5.0, 6.2, color="#f1c40f", alpha=0.09, zorder=1)
ax1.axhspan(6.2, 14, color="#e74c3c", alpha=0.09, zorder=1)
ax1.axhline(5.0, color="#27ae60", lw=1.5, ls="--", alpha=0.6)
ax1.axhline(6.2, color="#e74c3c", lw=1.5, ls="--", alpha=0.6)
ax1.axhline(3.0, color="#e67e22", lw=1.2, ls=":", alpha=0.7)

# подписи зон — справа, чтобы не мешать операции слева
ax1.text(
    datetime(2026, 5, 15),
    2.4,
    "Норма\n< 5.0",
    color="#27ae60",
    fontsize=13,
    weight="bold",
    ha="right",
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#27ae60", alpha=0.9),
)
ax1.text(
    datetime(2026, 5, 15),
    5.5,
    "Пограничный",
    color="#b7950b",
    fontsize=13,
    weight="bold",
    ha="right",
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#b7950b", alpha=0.9),
)
ax1.text(
    datetime(2026, 5, 15),
    10.8,
    "Высокий риск\n(> 6.2)",
    color="#c0392b",
    fontsize=13,
    weight="bold",
    ha="right",
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#c0392b", alpha=0.9),
)
ax1.text(datetime(2026, 5, 15), 3.15, "Цель ЛПНП < 3.0", color="#e67e22", fontsize=11, style="italic", ha="right")

# числовые подписи на точках
for d, y in zip(chol_x, chol_y):
    ax1.annotate(
        f"{y:.1f}",
        (d, y),
        textcoords="offset points",
        xytext=(0, 12),
        ha="center",
        fontsize=11,
        color="#c0392b",
        weight="bold",
    )

# «нет данных» зона до первого измерения
first_chol = chol_x[0]
ax1.axvspan(datetime(2014, 1, 1), first_chol, color="gray", alpha=0.08, zorder=0)
ax1.text(
    datetime(2014, 10, 1), 6.5, "Нет данных\nпо холестерину", fontsize=11, color="gray", ha="center", style="italic"
)

# --- события: расставлены по 3 уровням, чтобы не пересекались ---
events = [
    # (дата, подпись, цвет, y-уровень рамки)
    (datetime(2015, 10, 22), "Операция\nна гипофизе\n(22.10.2015)", "#8e44ad", 13.2),
    (datetime(2017, 1, 16), "L-тироксин 100 мкг\n(тиреотоксикоз)", "#2980b9", 14.8),
    (datetime(2017, 11, 1), "Доза ↓ 75 мкг", "#16a085", 13.2),
    (datetime(2018, 6, 6), "Короткий курс\nстатина?", "#27ae60", 14.8),
    (datetime(2021, 1, 15), "COVID-19", "#7f8c8d", 13.2),
    (datetime(2025, 11, 1), "Старт\nэзетимиба", "#16a085", 14.8),
    (datetime(2026, 3, 29), "+ бемпедоевая\nкислота", "#16a085", 13.2),
]
for ed, label, color, y_label in events:
    ax1.axvline(ed, color=color, lw=1.6, ls=":", alpha=0.7, zorder=2, ymin=0, ymax=0.92)
    ax1.annotate(
        label,
        xy=(ed, 12.7),
        xytext=(ed, y_label),
        fontsize=11.5,
        ha="center",
        va="center",
        color=color,
        weight="bold",
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=color, lw=1.3),
        arrowprops=dict(arrowstyle="-", color=color, lw=1.2),
    )

ax1.set_ylabel("ммоль/л", fontsize=15)
ax1.set_ylim(0, 16)
ax1.set_title("Холестерин Валерии Николаевны, 2015–2026 (10 лет наблюдений)", fontsize=19, weight="bold", pad=18)
ax1.legend(loc="lower left", framealpha=0.97, fontsize=13)
ax1.grid(True, alpha=0.3)

# --- нижняя панель ---
hdl_x, hdl_y = series("hdl")
tg_x, tg_y = series("tg")

ax2.plot(hdl_x, hdl_y, "^-", color="#2980b9", lw=2.4, markersize=9, label="ЛПВП («хороший», цель > 1.2)")
ax2.plot(tg_x, tg_y, "v-", color="#9b59b6", lw=2.4, markersize=9, label="Триглицериды (норма < 1.7)")
ax2.axhline(1.2, color="#2980b9", lw=1.3, ls="--", alpha=0.6)
ax2.axhline(1.7, color="#9b59b6", lw=1.3, ls="--", alpha=0.6)

for d, y in zip(hdl_x, hdl_y):
    ax2.annotate(
        f"{y:.2f}",
        (d, y),
        textcoords="offset points",
        xytext=(0, -18),
        ha="center",
        fontsize=10,
        color="#2980b9",
        weight="bold",
    )
for d, y in zip(tg_x, tg_y):
    ax2.annotate(
        f"{y:.2f}",
        (d, y),
        textcoords="offset points",
        xytext=(0, 10),
        ha="center",
        fontsize=10,
        color="#9b59b6",
        weight="bold",
    )

ax2.set_ylabel("ммоль/л", fontsize=15)
ax2.set_xlabel("Год", fontsize=15)
ax2.set_ylim(0, 4)
ax2.legend(loc="upper left", framealpha=0.97, fontsize=13)
ax2.grid(True, alpha=0.3)

# ось X
for ax in (ax1, ax2):
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 7]))
ax2.set_xlim(datetime(2015, 1, 1), datetime(2026, 7, 1))

plt.tight_layout()
plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight")
print(f"✅ Saved: {OUT_PATH}")
