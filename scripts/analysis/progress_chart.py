#!/opt/homebrew/bin/python3.13
"""
График прогресса HealthVault — 3 панели: вес+жир, калории, тренировки.
Сохраняет PNG в ~/Downloads/ и выводит путь.

Использование:
    python3 scripts/analysis/progress_chart.py
"""

import json, csv, statistics, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, date, timedelta
from pathlib import Path
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

BASE = Path(__file__).parent.parent.parent
START = date(2026, 1, 6)
TODAY = date.today()
GOAL_DATE = date(2026, 5, 15)
GOAL_WEIGHT = 75.0
XLIM = (START - timedelta(days=1), GOAL_DATE + timedelta(days=5))

def pd(s):
    try: return datetime.strptime(s.strip()[:10], '%Y-%m-%d').date()
    except: return None

# === LOAD WEIGHT & FAT (Zepp) ===
weight = {}; fat = {}
zepp_file = BASE / "data/zepp_export_latest.csv"
if zepp_file.exists():
    with open(zepp_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = pd(row.get("Date", ""))
            if dt and dt >= START:
                try: weight[dt] = float(row["Weight"])
                except: pass
                try:
                    bf = float(row["BodyFat"])
                    if bf > 0: fat[dt] = bf
                except: pass

# === LOAD NUTRITION ===
nutrition = {}
# Try server-synced CSV first
nut_csv = Path("/tmp/hv_nutrition_daily.csv")
if not nut_csv.exists():
    # Rebuild from daily dump JSONs
    nut_dir = BASE / "data/nutrition"
    if nut_dir.exists():
        for f_path in sorted(nut_dir.glob("*.json")):
            dt = pd(f_path.stem)
            if dt and dt >= START:
                try:
                    d = json.loads(f_path.read_text())
                    cal = d.get("total_calories") or d.get("calories")
                    if cal: nutrition[dt] = float(cal)
                except: pass
else:
    with open(nut_csv) as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                dt = pd(parts[0])
                if dt and dt >= START:
                    try: nutrition[dt] = float(parts[1])
                    except: pass

# === LOAD TRAINING (Garmin) ===
training_dates = set()
act_dir = BASE / "data/garmin/activities"
if act_dir.exists():
    for f_path in act_dir.glob("*.json"):
        try:
            d = json.loads(f_path.read_text())
            dt = pd(d.get("startTimeLocal", ""))
            if dt and dt >= START:
                training_dates.add(dt)
        except: pass

# === ALCOHOL DAYS (ручной лог) ===
alcohol_days = {
    date(2026,1,16): 3, date(2026,1,23): 1, date(2026,2,7): 5,
    date(2026,2,14): 1, date(2026,2,17): 1, date(2026,2,21): 2,
    date(2026,3,5): 1, date(2026,3,15): 1, date(2026,3,17): 1,
    date(2026,3,19): 2, date(2026,3,24): 1,
}

def ma7(data_dict):
    all_dates = sorted(data_dict.keys())
    if not all_dates: return [], []
    dates_out = []; vals_out = []
    for i, d in enumerate(all_dates):
        window = [data_dict[dd] for dd in all_dates[max(0,i-6):i+1]]
        dates_out.append(d); vals_out.append(sum(window)/len(window))
    return dates_out, vals_out

w_dates, w_vals = ma7(weight)
f_dates, f_vals = ma7(fat)

raw_wd = sorted(weight.keys())
raw_wv = [weight[d] for d in raw_wd]
first_w = raw_wv[0]; last_w = raw_wv[-1]; delta_w = first_w - last_w

# === COLOURS ===
c = {
    'w': '#4FC3F7', 'fat': '#CE93D8', 'goal': '#66BB6A',
    'cal': '#FFB74D', 'cal_hi': '#FF7043', 'cal_lo': '#66BB6A',
    'alc': '#F44336', 'train': '#4CAF50',
    'grid': '#2a2a4a', 'txt': '#e0e0e0'
}

# === Нормализация жира к шкале веса (z-score) ===
w_mean = statistics.mean(w_vals)
w_std  = statistics.stdev(w_vals) if len(w_vals) > 1 else 1
f_mean = statistics.mean(f_vals)
f_std  = statistics.stdev(f_vals) if len(f_vals) > 1 else 1
fat_norm = [w_mean + (fv - f_mean) * (w_std / f_std) for fv in f_vals]

# === PLOT ===
fig, axes = plt.subplots(3, 1, figsize=(16, 11),
                         gridspec_kw={'height_ratios': [3, 2, 0.35]},
                         sharex=True)
fig.patch.set_facecolor('#1a1a2e')

# --- Panel 1: Weight + Fat (normalized) ---
ax1 = axes[0]; ax1.set_facecolor('#16213e')
ax1.plot(w_dates, w_vals, color=c['w'], linewidth=2.5)
ax1.scatter(raw_wd, raw_wv, color=c['w'], alpha=0.2, s=15, zorder=2)
ax1.plot(f_dates, fat_norm, color=c['fat'], linewidth=2, alpha=0.85)

# Правая ось — реальный % жира
ax2 = ax1.twinx()
ax2.set_ylabel('Жир, %', color=c['fat'], fontsize=12)
ax2.tick_params(colors=c['fat'])

# Проекция цели
ax1.plot([raw_wd[-1], GOAL_DATE], [last_w, GOAL_WEIGHT],
         color=c['goal'], linestyle='--', linewidth=1.8, alpha=0.85)
ax1.annotate('49 лет\n75 кг', xy=(GOAL_DATE, GOAL_WEIGHT),
             xytext=(GOAL_DATE - timedelta(days=8), GOAL_WEIGHT + 1.8),
             color=c['goal'], fontsize=10, fontweight='bold', ha='center',
             arrowprops=dict(arrowstyle='->', color=c['goal'], alpha=0.7))

# Alcohol markers
for d, drinks in alcohol_days.items():
    if d in weight:
        ax1.scatter(d, weight[d], color=c['alc'], s=40+drinks*25, marker='v', zorder=5, alpha=0.8)

ax1.set_ylabel('Вес, кг', color=c['w'], fontsize=12)
ax1.tick_params(colors=c['txt'])
ax1.grid(True, alpha=0.15, color=c['grid'])

# Аннотация старта
ax1.annotate(f'{first_w:.1f} кг', xy=(raw_wd[0], first_w),
             xytext=(raw_wd[0], first_w + 1.0),
             color=c['w'], fontsize=10, ha='center',
             arrowprops=dict(arrowstyle='->', color=c['w'], alpha=0.5))

first_f = f_vals[0] if f_vals else None
if first_f:
    ax1.annotate(f'{first_f:.1f}%', xy=(f_dates[0], fat_norm[0]),
                 xytext=(f_dates[0] + timedelta(days=6), fat_norm[0] + 1.0),
                 color=c['fat'], fontsize=10, ha='center',
                 arrowprops=dict(arrowstyle='->', color=c['fat'], alpha=0.5))

# Аннотация текущего веса (вниз)
ax1.annotate(f'{last_w:.1f} кг', xy=(raw_wd[-1], last_w),
             xytext=(raw_wd[-1], last_w - 1.2),
             color=c['w'], fontsize=11, fontweight='bold', ha='center',
             arrowprops=dict(arrowstyle='->', color=c['w'], alpha=0.7))

# Аннотация текущего жира (вверх, смещена влево)
cur_fat = f_vals[-1] if f_vals else None
if cur_fat:
    ax1.annotate(f'{cur_fat:.1f}%', xy=(f_dates[-1], fat_norm[-1]),
                 xytext=(f_dates[-1] - timedelta(days=12), fat_norm[-1] + 1.5),
                 color=c['fat'], fontsize=10, fontweight='bold', ha='center',
                 arrowprops=dict(arrowstyle='->', color=c['fat'], alpha=0.7))

ax1.set_title(
    f'HealthVault · -{delta_w:.1f} кг за {(TODAY-START).days} дней · Цель {GOAL_WEIGHT} кг к 15 мая',
    color=c['txt'], fontsize=14, fontweight='bold', pad=15)

legend_els = [
    Line2D([0],[0], color=c['w'], linewidth=2.5, label='Вес (7д MA)'),
    Line2D([0],[0], color=c['fat'], linewidth=2, alpha=0.85, label='Жир % (7д MA)'),
    Line2D([0],[0], color=c['goal'], linestyle='--', linewidth=1.8, label='Цель 75 кг'),
    Line2D([0],[0], marker='v', color=c['alc'], linestyle='None', markersize=8, label='Алкоголь'),
]
ax1.legend(handles=legend_els, loc='upper right', fontsize=9,
           facecolor='#16213e', edgecolor='#333', labelcolor=c['txt'], framealpha=0.9)

# Синхронизация правой оси
ax1.autoscale(enable=True, axis='y')
y1_min, y1_max = ax1.get_ylim()
f_at_bottom = f_mean + (y1_min - w_mean) * (f_std / w_std)
f_at_top    = f_mean + (y1_max - w_mean) * (f_std / w_std)
ax2.set_ylim(f_at_bottom, f_at_top)

# --- Panel 2: Calories ---
ax3 = axes[1]; ax3.set_facecolor('#16213e')
cal_dates = sorted(nutrition.keys())
cal_vals = [nutrition[d] for d in cal_dates]
bar_colors = [c['cal_hi'] if v > 2500 else c['cal_lo'] if v < 1500 else c['cal'] for v in cal_vals]
ax3.bar(cal_dates, cal_vals, color=bar_colors, alpha=0.7, width=0.8)
ax3.axhline(y=2000, color='#FF5252', linestyle='--', alpha=0.6, linewidth=1.5)
cal_ma_d, cal_ma_v = ma7(nutrition)
ax3.plot(cal_ma_d, cal_ma_v, color='white', linewidth=1.5, alpha=0.6)
avg_cal = sum(cal_vals)/len(cal_vals) if cal_vals else 0
ax3.set_ylabel('Ккал/день', color=c['cal'], fontsize=12)
ax3.set_title(f'Калорийность · Среднее: {avg_cal:.0f} ккал/день', color=c['txt'], fontsize=12, pad=8)
ax3.tick_params(colors=c['txt']); ax3.grid(True, alpha=0.15, color=c['grid'])
ax3.set_ylim(0, max(cal_vals)*1.1 if cal_vals else 3000)

cal_legend = [
    Patch(facecolor=c['cal'], alpha=0.7, label='Норма (1500–2500)'),
    Patch(facecolor=c['cal_hi'], alpha=0.7, label='Перебор (>2500)'),
    Patch(facecolor=c['cal_lo'], alpha=0.7, label='Дефицит (<1500)'),
    Line2D([0],[0], color='white', linewidth=1.5, alpha=0.6, label='7д среднее'),
    Line2D([0],[0], color='#FF5252', linestyle='--', linewidth=1.5, alpha=0.6, label='Цель 2000'),
]
ax3.legend(handles=cal_legend, loc='upper right', fontsize=8,
           facecolor='#16213e', edgecolor='#333', labelcolor=c['txt'], framealpha=0.9, ncol=5)

# --- Panel 3: Training ---
ax4 = axes[2]; ax4.set_facecolor('#16213e')
all_days = [START + timedelta(days=i) for i in range((TODAY-START).days+1)]
for d in all_days:
    if d in training_dates:
        ax4.scatter(d, 0.5, color=c['train'], s=60, marker='s', alpha=0.8, zorder=3)
ax4.set_yticks([0.5])
ax4.set_yticklabels(['Спорт'], color=c['txt'], fontsize=10)
ax4.set_ylim(0, 1)
ax4.tick_params(colors=c['txt']); ax4.grid(True, alpha=0.15, color=c['grid'])
train_count = len(training_dates); weeks = (TODAY-START).days/7
ax4.set_title(f'{train_count} тренировок ({train_count/weeks:.1f}/нед)',
              color=c['txt'], fontsize=11, pad=4)

# Shared x-axis
for ax in axes:
    ax.set_xlim(XLIM)
axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
axes[-1].xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
axes[-1].tick_params(axis='x', colors=c['txt'], rotation=0)

plt.tight_layout(h_pad=0.5)

# === SAVE ===
date_str = TODAY.strftime('%d%b').lower()
out = Path.home() / "Downloads" / f"HealthVault_progress_{date_str}.png"
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f"OK: {out}")
