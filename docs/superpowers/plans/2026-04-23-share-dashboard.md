# Share Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каждый пользователь HealthVault может получить секретную ссылку `https://health.orangegate.cc/mc/{uuid}` на свой персональный дашборд здоровья и поделиться ею с друзьями.

**Architecture:** Пользователь пишет `/share` → бот генерирует UUID, сохраняет в `users.share_token` → присылает URL. При открытии URL FastAPI читает данные пользователя из PostgreSQL и рендерит HTML на лету — данные всегда свежие, кнопка «обновить» не нужна.

**Tech Stack:** Python 3.11+, FastAPI (уже запущен в `apple_health.py`), SQLAlchemy, aiogram 3.x, PostgreSQL, uvicorn на порту 8081.

---

## File Map

| Файл | Действие | Ответственность |
|---|---|---|
| `telegram-bot/webhook/dashboard.py` | **Создать** | FastAPI endpoint `GET /mc/{token}` |
| `telegram-bot/dashboard_generator.py` | **Создать** | Агрегация данных из БД + генерация HTML |
| `database/models.py` | **Изменить** | Добавить `share_token` в `User` |
| `database/crud.py` | **Изменить** | Добавить `generate_share_token`, `get_user_by_share_token` |
| `database/__init__.py` | **Изменить** | Экспортировать новые CRUD-функции |
| `telegram-bot/handlers/commands.py` | **Изменить** | Добавить `/share` команду |
| `telegram-bot/webhook/apple_health.py` | **Изменить** | `app.include_router(dashboard_router)` |

---

## Task 1: Добавить `share_token` в БД

**Files:**
- Modify: `database/models.py` — добавить поле `share_token` в класс `User`
- Modify: `database/crud.py` — добавить `generate_share_token`, `get_user_by_share_token`
- Modify: `database/__init__.py` — экспорт новых функций

- [ ] **1.1 Добавить поле в модель User**

В `database/models.py`, в класс `User` после строки с `health_token`:
```python
# Share token for public dashboard (security by obscurity)
share_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
```

- [ ] **1.2 Добавить CRUD-функции в crud.py**

В `database/crud.py` после функции `generate_health_token` (строка ~97):
```python
def get_user_by_share_token(db: Session, share_token: str) -> Optional[User]:
    """Get user by share dashboard token"""
    return db.query(User).filter(User.share_token == share_token).first()


def generate_share_token(db: Session, telegram_id: int) -> str:
    """Generate and save a unique share token for user's public dashboard.

    Idempotent: if user already has a token, returns it unchanged.
    Call reset_share_token() to force-regenerate.
    """
    import uuid
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError(f"User {telegram_id} not found")
    if user.share_token:
        return user.share_token
    user.share_token = str(uuid.uuid4())
    db.commit()
    return user.share_token


def reset_share_token(db: Session, telegram_id: int) -> str:
    """Regenerate share token — old URL immediately stops working."""
    import uuid
    user = get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise ValueError(f"User {telegram_id} not found")
    user.share_token = str(uuid.uuid4())
    db.commit()
    return user.share_token
```

- [ ] **1.3 Экспортировать из `database/__init__.py`**

В секцию `# User operations` в `from database.crud import (...)` добавить:
```python
    get_user_by_share_token,
    generate_share_token,
    reset_share_token,
```

В список `__all__` добавить те же три имени.

- [ ] **1.4 Накатить ALTER TABLE на сервере**

```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
   'ALTER TABLE users ADD COLUMN IF NOT EXISTS share_token VARCHAR(64) UNIQUE;'"
```

Ожидаемый вывод: `ALTER TABLE`

- [ ] **1.5 Проверить колонку**

```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
   \"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='users' AND column_name='share_token';\""
```

Ожидаемый вывод: строка `share_token | character varying`

- [ ] **1.6 Коммит**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git add database/models.py database/crud.py database/__init__.py
git commit -m "feat: add share_token to User model + CRUD helpers"
```

---

## Task 2: HTML-генератор (данные из PostgreSQL → HTML-строка)

**Files:**
- Create: `telegram-bot/dashboard_generator.py`

Генератор читает данные пользователя из БД и возвращает строку HTML — тот же дизайн Mission Control (dark, зелёный акцент), но без разделов, которых нет у конкретного пользователя.

- [ ] **2.1 Создать `telegram-bot/dashboard_generator.py`**

```python
"""
HealthVault Share Dashboard Generator
Читает данные пользователя из PostgreSQL → возвращает HTML-строку.
Дизайн: тёмный Mission Control, зелёный #00ff9d акцент.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session


# ── Data aggregation ──────────────────────────────────────────────────────────

def _collect_user_data(db: Session, user_id: int) -> dict:
    """Агрегирует данные пользователя из БД за всё время.

    Returns dict с ключами:
      meta, weight, nutrition, supplements, activity, display_name
    """
    from database.crud import (
        get_user_by_telegram_id,
        get_weights_by_period,
        get_nutrition_logs_by_period,
        get_supplements_by_period,
        get_activities_by_period,
    )

    user = get_user_by_telegram_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    display_name = user.first_name or user.username or f"User {user_id}"
    today = date.today()
    # Start from registration or 2026-01-06 (project start), whichever is later
    project_start = date(2026, 1, 6)
    registered = user.registered_at.date() if user.registered_at else project_start
    start = max(project_start, registered)
    total_days = (today - start).days + 1

    # ── Weight (get_weights_by_period expects datetime) ──
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())
    weights = get_weights_by_period(db, user_id, start_dt, end_dt)
    weight_series = {}  # date_str → weight kg
    fat_series = {}
    for w in weights:
        d = w.measured_at.date().isoformat()
        weight_series[d] = round(w.weight, 2)
        if w.body_fat is not None:
            fat_series[d] = round(w.body_fat, 1)

    # ── Nutrition ──
    nutrition_logs = get_nutrition_logs_by_period(db, user_id, start, today)
    kcal_series = {}
    prot_series = {}
    for log in nutrition_logs:
        d = log.date.isoformat()
        totals = log.totals or {}
        kcal_series[d] = kcal_series.get(d, 0) + (totals.get("calories") or 0)
        prot_series[d] = prot_series.get(d, 0) + (totals.get("protein") or 0)
    # Round
    kcal_series = {k: round(v) for k, v in kcal_series.items() if v > 0}
    prot_series = {k: round(v, 1) for k, v in prot_series.items() if v > 0}

    # ── Supplements ──
    supps = get_supplements_by_period(db, user_id, start, today)
    supp_days = sorted(set(s.date.isoformat() for s in supps))

    # ── Activity (sleep, steps, HRV from raw_data) ──
    activities = get_activities_by_period(db, user_id, start, today)
    sleep_series = {}
    steps_series = {}
    hrv_series = {}
    stress_series = {}
    bb_series = {}
    rhr_series = {}
    for a in activities:
        d = a.date.isoformat()
        if a.sleep_hours:
            sleep_series[d] = round(a.sleep_hours, 1)
        if a.steps:
            steps_series[d] = a.steps
        if a.hrv:
            hrv_series[d] = a.hrv
        if a.stress_level:
            stress_series[d] = a.stress_level
        if a.heart_rate_avg:
            rhr_series[d] = a.heart_rate_avg
        # Body Battery from raw_data (Garmin users)
        if a.raw_data:
            bb = a.raw_data.get("body_battery_max")
            if bb:
                bb_series[d] = bb

    # ── Weight stats ──
    stats_weight: dict = {}
    if weight_series:
        vals = list(weight_series.values())
        first_date = min(weight_series.keys())
        last_date = max(weight_series.keys())
        stats_weight = {
            "first": weight_series[first_date],
            "last": weight_series[last_date],
            "min": min(vals),
            "max": max(vals),
            "delta": round(weight_series[last_date] - weight_series[first_date], 2),
        }

    target_weight = (user.target_weight_kg or
                     (db.query(__import__('database.models', fromlist=['UserSettings']).UserSettings)
                      .filter_by(user_id=user_id).first() or type('', (), {'target_weight_kg': None})()).target_weight_kg)

    return {
        "meta": {
            "user_id": user_id,
            "display_name": display_name,
            "today": today.isoformat(),
            "start": start.isoformat(),
            "total_days": total_days,
            "generated_at": datetime.now().isoformat(),
        },
        "weight": weight_series,
        "fat": fat_series,
        "stats_weight": stats_weight,
        "target_weight": target_weight,
        "kcal": kcal_series,
        "prot": prot_series,
        "supp_days": supp_days,
        "sleep_h": sleep_series,
        "steps": steps_series,
        "hrv": hrv_series,
        "stress": stress_series,
        "body_battery": bb_series,
        "rhr": rhr_series,
    }


# ── HTML builder ──────────────────────────────────────────────────────────────

def generate_dashboard_html(db: Session, user_id: int) -> str:
    """Главная функция: данные из БД → HTML-строка для отдачи через FastAPI."""
    data = _collect_user_data(db, user_id)
    return _render_html(data)


def _render_html(data: dict) -> str:
    import json
    meta = data["meta"]
    sw = data["stats_weight"]
    display_name = meta["display_name"]
    today_str = meta["today"]
    start_str = meta["start"]
    total_days = meta["total_days"]
    generated_at = meta["generated_at"][:16].replace("T", " ")

    # Compute averages
    def avg(d: dict) -> float:
        return round(sum(d.values()) / len(d), 1) if d else 0

    sleep_avg = avg(data["sleep_h"])
    hrv_avg = int(avg(data["hrv"])) if data["hrv"] else 0
    stress_avg = int(avg(data["stress"])) if data["stress"] else 0
    rhr_avg = int(avg(data["rhr"])) if data["rhr"] else 0
    steps_avg = int(avg(data["steps"])) if data["steps"] else 0
    bb_avg = int(avg(data["body_battery"])) if data["body_battery"] else 0
    kcal_avg = int(avg(data["kcal"])) if data["kcal"] else 0
    prot_avg = avg(data["prot"]) if data["prot"] else 0
    supp_days_n = len(data["supp_days"])

    weight_last = sw.get("last", "—")
    weight_delta = sw.get("delta", 0)
    fat_vals = list(data["fat"].values())
    fat_last = round(fat_vals[-1], 1) if fat_vals else None
    target_w = data.get("target_weight")

    # Sections to show (only if data exists)
    show_weight = bool(data["weight"])
    show_nutrition = bool(data["kcal"])
    show_activity = bool(data["sleep_h"] or data["steps"] or data["hrv"])
    show_supps = supp_days_n > 0

    # Serialize for JS
    js_data = json.dumps({
        "meta": meta,
        "weight": data["weight"],
        "fat": data["fat"],
        "stats_weight": sw,
        "kcal": data["kcal"],
        "prot": data["prot"],
        "sleep_h": data["sleep_h"],
        "steps": data["steps"],
        "hrv": data["hrv"],
        "stress": data["stress"],
        "body_battery": data["body_battery"],
        "rhr": data["rhr"],
        "supp_days_n": supp_days_n,
    }, ensure_ascii=False)

    delta_sign = "↓" if weight_delta < 0 else "↑"
    delta_color = "g" if weight_delta < 0 else "r"

    # Build stream cards (only for available data)
    stream_cards = ""
    streams = []
    if data["sleep_h"]:
        streams.append(("😴", "Сон", sleep_avg, "ч ср", "sleep_h", "#a78bfa"))
    if data["hrv"]:
        streams.append(("💗", "HRV", hrv_avg, "мс ср", "hrv", "#f43f5e"))
    if data["stress"]:
        streams.append(("😰", "Стресс", stress_avg, "/100", "stress", "#fbbf24"))
    if data["rhr"]:
        streams.append(("💓", "Пульс покоя", rhr_avg, "уд/мин", "rhr", "#f43f5e"))
    if data["steps"]:
        streams.append(("👣", "Шаги", f"{steps_avg:,}", "/день ср", "steps", "#00ff9d"))
    if data["body_battery"]:
        streams.append(("🔋", "Body Battery", bb_avg, "max ср", "body_battery", "#00ff9d"))
    if data["kcal"]:
        streams.append(("🍽️", "КБЖУ дней", len(data["kcal"]), f"/{total_days}", "kcal", "#3b82f6"))
    if data["prot"]:
        streams.append(("🥩", "Белок", prot_avg, "г/день ср", "prot", "#fbbf24"))
    if show_supps:
        streams.append(("💊", "Добавки", supp_days_n, "дней", None, "#a78bfa"))

    for emoji, name, val, unit, key, color in streams:
        spark_html = f'<canvas id="spark_{key}" class="spark"></canvas>' if key else ""
        stream_cards += f"""
    <div class="stream">
      <div class="name">{emoji} {name}</div>
      <div class="val-row"><span class="val">{val}</span><span class="unit">{unit}</span></div>
      {spark_html}
    </div>"""

    grid_cols = min(len(streams), 6) if streams else 3
    stream_section = ""
    if streams:
        stream_section = f"""
<div class="section-title">ПОТОКИ ДАННЫХ <span class="hint">с {start_str}</span></div>
<div class="grid" style="grid-template-columns: repeat({grid_cols}, minmax(0,1fr)); gap:14px;" id="streams-grid">
  {stream_cards}
</div>"""

    # Weight section
    weight_section = ""
    if show_weight:
        delta_pill = f'<span class="delta-pill {delta_color}">{delta_sign} {abs(weight_delta)} кг</span>' if weight_delta else ""
        target_line = f'<div class="sub">цель {target_w} кг · T−<span id="cd-days">—</span> дн</div>' if target_w else ""
        fat_line = f'<div class="sub">Жир: {fat_last}%</div>' if fat_last else ""
        weight_section = f"""
<div class="section-title">ВЕС <span class="hint">с {start_str}</span></div>
<div class="card" style="padding:20px;">
  <div style="font-size:42px;font-weight:800;line-height:1;">{weight_last} <span style="font-size:18px;color:var(--muted)">кг</span> {delta_pill}</div>
  {fat_line}
  {target_line}
  <div class="chart-wrap" style="height:200px;margin-top:16px;"><canvas id="weightChart"></canvas></div>
</div>"""

    # Nutrition section
    nutrition_section = ""
    if show_nutrition:
        nutrition_section = f"""
<div class="section-title">ПИТАНИЕ <span class="hint">среднее {kcal_avg} ккал · {prot_avg}г белка</span></div>
<div class="card" style="padding:20px;">
  <div class="chart-wrap" style="height:180px;"><canvas id="nutritionChart"></canvas></div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HealthVault · {display_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
:root {{
  --bg: #0a0e17; --card: #111827; --border: #1f2940;
  --g: #00ff9d; --r: #ff3b6d; --y: #fbbf24; --b: #3b82f6; --p: #a78bfa;
  --text: #e8eef7; --muted: #7a879f;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg); color: var(--text);
  font-family: 'SF Pro Display','Inter',-apple-system,sans-serif;
  font-size: 14px; line-height: 1.4; padding: 20px;
  background-image:
    radial-gradient(circle at 20% 0%, rgba(0,255,157,.03) 0%, transparent 50%),
    radial-gradient(circle at 80% 100%, rgba(168,85,247,.03) 0%, transparent 50%);
}}
.topbar {{
  display:flex; justify-content:space-between; align-items:center;
  padding:14px 20px; background:var(--card);
  border:1px solid var(--border); border-radius:12px; margin-bottom:20px;
  position:relative; overflow:hidden;
}}
.topbar::before {{
  content:''; position:absolute; inset:0;
  background:linear-gradient(90deg,transparent 0%,rgba(0,255,157,.06) 50%,transparent 100%);
  animation:scan 8s linear infinite;
}}
@keyframes scan {{ 0% {{ transform:translateX(-100%); }} 100% {{ transform:translateX(100%); }} }}
.logo {{ font-size:20px; font-weight:800; letter-spacing:-.5px; }}
.logo .accent {{ color:var(--g); }}
.meta-info {{ font-size:11px; color:var(--muted); text-align:right; line-height:1.8; }}
.dot {{ display:inline-block; width:7px; height:7px; border-radius:50%;
        background:var(--g); box-shadow:0 0 10px var(--g); animation:pulse 2s ease-in-out infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.3; }} }}
.grid {{ display:grid; gap:14px; }}
.card {{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:16px; position:relative; overflow:hidden;
}}
.section-title {{
  font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:2px;
  color:var(--text); margin:28px 0 12px; display:flex; align-items:center; gap:10px;
}}
.section-title::before {{ content:''; width:4px; height:14px; background:var(--g); border-radius:2px; }}
.section-title .hint {{ font-size:10px; font-weight:400; color:var(--muted);
                        text-transform:none; letter-spacing:.3px; margin-left:8px; }}
.stream {{
  background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:12px 14px;
}}
.stream .name {{ font-size:10px; color:var(--muted); text-transform:uppercase;
                 letter-spacing:1px; margin-bottom:4px; }}
.stream .val-row {{ display:flex; align-items:baseline; gap:4px; }}
.stream .val {{ font-size:22px; font-weight:700; line-height:1.1; }}
.stream .unit {{ font-size:11px; color:var(--muted); font-weight:400; }}
.stream .spark {{ height:28px; margin-top:6px; }}
.chart-wrap {{ position:relative; }}
.delta-pill {{
  display:inline-block; font-size:12px; font-weight:600; padding:3px 9px;
  border-radius:20px; margin-left:8px; vertical-align:middle;
}}
.delta-pill.g {{ background:rgba(0,255,157,.12); color:var(--g); }}
.delta-pill.r {{ background:rgba(255,59,109,.12); color:var(--r); }}
.sub {{ font-size:12px; color:var(--muted); margin-top:6px; }}
footer {{
  margin-top:40px; text-align:center;
  font-size:11px; color:var(--muted); opacity:.5;
}}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <div class="logo">Health<span class="accent">Vault</span></div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px;">{display_name}</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px;">
    <div class="dot"></div>
    <div class="meta-info">
      {total_days} дней наблюдений · обновлено {generated_at}
    </div>
  </div>
</div>

{stream_section}
{weight_section}
{nutrition_section}

<footer>HealthVault · персональный дашборд · данные обновляются при каждом открытии</footer>

<script>
const D = {js_data};
const COLOR = {{ g:'#00ff9d', r:'#ff3b6d', y:'#fbbf24', b:'#3b82f6', p:'#a78bfa',
                 muted:'#7a879f', grid:'#1f2940', text:'#e8eef7' }};

Chart.defaults.color = COLOR.muted;
Chart.defaults.font.family = "'SF Pro Display','Inter',sans-serif";
Chart.defaults.font.size = 10;
Chart.defaults.borderColor = COLOR.grid;

function toPoints(obj) {{
  return Object.entries(obj).sort().map(([x,y]) => ({{x, y}}));
}}

// Sparklines
const sparkConfigs = {{
  sleep_h: COLOR.p, hrv: COLOR.r, stress: COLOR.y,
  rhr: COLOR.r, steps: COLOR.g, body_battery: COLOR.g,
  kcal: COLOR.b, prot: COLOR.y,
}};
Object.entries(sparkConfigs).forEach(([key, color]) => {{
  const el = document.getElementById('spark_' + key);
  if (!el || !D[key] || !Object.keys(D[key]).length) return;
  new Chart(el, {{
    type: 'line',
    data: {{ datasets: [{{ data: toPoints(D[key]), borderColor: color,
                           borderWidth: 1.5, pointRadius: 0, tension: 0.3,
                           fill: true,
                           backgroundColor: color.replace(')', ',.06)').replace('rgb', 'rgba') }}] }},
    options: {{
      animation: false, responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
      scales: {{
        x: {{ type: 'time', display: false }},
        y: {{ display: false }},
      }}
    }}
  }});
}});

// Weight chart
const weightEl = document.getElementById('weightChart');
if (weightEl && Object.keys(D.weight).length) {{
  const datasets = [{{
    label: 'Вес, кг', data: toPoints(D.weight),
    borderColor: COLOR.g, borderWidth: 2, pointRadius: 0,
    tension: 0.3, yAxisID: 'yW',
    fill: true, backgroundColor: 'rgba(0,255,157,.06)',
  }}];
  if (Object.keys(D.fat).length) {{
    datasets.push({{
      label: 'Жир, %', data: toPoints(D.fat),
      borderColor: COLOR.y, borderWidth: 1.5, pointRadius: 0,
      tension: 0.3, yAxisID: 'yF', borderDash: [4,3],
    }});
  }}
  new Chart(weightEl, {{
    type: 'line', data: {{ datasets }},
    options: {{
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: true, position: 'top',
                   labels: {{ color: COLOR.muted, boxWidth: 12, font: {{ size: 10 }} }} }},
        tooltip: {{ backgroundColor: '#0a0e17', borderColor: COLOR.grid, borderWidth: 1 }},
      }},
      scales: {{
        x: {{ type: 'time', time: {{ unit: 'week', displayFormats: {{ week: 'dd.MM' }} }},
              grid: {{ display: false }} }},
        yW: {{ position: 'left', grid: {{ color: COLOR.grid }} }},
        yF: {{ position: 'right', grid: {{ display: false }} }},
      }}
    }}
  }});

  // T-minus countdown
  const cdEl = document.getElementById('cd-days');
  if (cdEl && D.meta.target_weight_kg) {{
    const sw = D.stats_weight;
    if (sw.last && sw.delta < 0) {{
      const ratePerDay = sw.delta / D.meta.total_days;
      const remaining = D.meta.target_weight_kg - sw.last;
      const daysLeft = ratePerDay < 0 ? Math.round(remaining / ratePerDay) : null;
      cdEl.textContent = daysLeft && daysLeft > 0 ? daysLeft : '—';
    }}
  }}
}}

// Nutrition chart
const nutEl = document.getElementById('nutritionChart');
if (nutEl && Object.keys(D.kcal).length) {{
  new Chart(nutEl, {{
    type: 'bar', data: {{
      datasets: [{{
        label: 'Ккал', data: toPoints(D.kcal),
        backgroundColor: 'rgba(59,130,246,.6)', borderWidth: 0, borderRadius: 2,
      }}]
    }},
    options: {{
      animation: false, responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#0a0e17', borderColor: COLOR.grid, borderWidth: 1 }},
      }},
      scales: {{
        x: {{ type: 'time', time: {{ unit: 'week', displayFormats: {{ week: 'dd.MM' }} }},
              grid: {{ display: false }} }},
        y: {{ grid: {{ color: COLOR.grid }} }},
      }}
    }}
  }});
}}
</script>
</body>
</html>"""
```

- [ ] **2.2 Коммит**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git add telegram-bot/dashboard_generator.py
git commit -m "feat: add dashboard HTML generator (PostgreSQL → HTML)"
```

---

## Task 3: FastAPI endpoint `GET /mc/{token}`

**Files:**
- Create: `telegram-bot/webhook/dashboard.py`
- Modify: `telegram-bot/webhook/apple_health.py` — одна строка include_router

- [ ] **3.1 Создать `telegram-bot/webhook/dashboard.py`**

```python
"""
HealthVault Share Dashboard — FastAPI endpoint.
GET /mc/{token} → HTML дашборд пользователя
"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/mc/{token}", response_class=HTMLResponse, include_in_schema=False)
async def share_dashboard(token: str):
    """Render personal health dashboard for the given share token.

    Returns 404 for unknown/invalid tokens (no hints about why).
    """
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import get_user_by_share_token
    from dashboard_generator import generate_dashboard_html

    db = SessionLocal()
    try:
        user = get_user_by_share_token(db, token)
        if not user or not user.is_active:
            raise HTTPException(status_code=404, detail="Not found")
        html = generate_dashboard_html(db, user.telegram_id)
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard render error for token {token[:8]}…: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()
```

- [ ] **3.2 Зарегистрировать router в `apple_health.py`**

В `telegram-bot/webhook/apple_health.py`, после строки `app.include_router(supplements_router)` (ищи её в конце файла, рядом с `nutrition_router`), добавить:

```python
from webhook.dashboard import router as dashboard_router
app.include_router(dashboard_router)
```

- [ ] **3.3 Коммит**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git add telegram-bot/webhook/dashboard.py telegram-bot/webhook/apple_health.py
git commit -m "feat: add GET /mc/{token} FastAPI endpoint for share dashboard"
```

---

## Task 4: Бот-команда `/share`

**Files:**
- Modify: `telegram-bot/handlers/commands.py`
- Modify: `telegram-bot/bot.py` — добавить share в список команд

- [ ] **4.1 Добавить handler в `commands.py`**

В `telegram-bot/handlers/commands.py`, после последнего `@router.message(Command(...))` блока, добавить:

```python
@router.message(Command("share"))
async def cmd_share(message: Message, user_id: int):
    """Создаёт/показывает секретную ссылку на персональный дашборд.

    /share          — показать/создать ссылку
    /share reset    — пересоздать ссылку (старая перестаёт работать)
    """
    from database import SessionLocal
    from database.crud import generate_share_token, reset_share_token
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    args = message.text.split()[1:] if message.text else []
    do_reset = args and args[0].lower() == "reset"

    db = SessionLocal()
    try:
        if do_reset:
            token = reset_share_token(db, user_id)
            action_text = "🔁 Ссылка пересоздана — старая больше не работает."
        else:
            token = generate_share_token(db, user_id)
            action_text = "📊 Твой персональный дашборд здоровья:"
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return
    finally:
        db.close()

    url = f"https://health.orangegate.cc/mc/{token}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔗 Открыть дашборд", url=url),
    ]])

    await message.answer(
        f"{action_text}\n\n"
        f"<code>{url}</code>\n\n"
        f"Кидай ссылку друзьям — дашборд обновляется автоматически при каждом открытии.\n"
        f"Хочешь сменить ссылку (старая перестанет работать)? Напиши /share reset",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
```

- [ ] **4.2 Добавить `/share` в список команд бота**

В `telegram-bot/bot.py`, в список `commands = [...]` добавить:
```python
BotCommand(command="share", description="Поделиться дашбордом здоровья"),
```

- [ ] **4.3 Коммит**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git add telegram-bot/handlers/commands.py telegram-bot/bot.py
git commit -m "feat: add /share command to bot — generates share link for health dashboard"
```

---

## Task 5: Деплой на сервер

- [ ] **5.1 Накатить ALTER TABLE (если не сделано в Task 1)**

```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
   'ALTER TABLE users ADD COLUMN IF NOT EXISTS share_token VARCHAR(64) UNIQUE;'"
```

- [ ] **5.2 Запушить код в git**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git push origin main
```

- [ ] **5.3 Скопировать новые файлы на сервер**

```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' scp \
  "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine/telegram-bot/dashboard_generator.py" \
  root@116.203.213.137:/app/telegram-bot/dashboard_generator.py

/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' scp \
  "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine/telegram-bot/webhook/dashboard.py" \
  root@116.203.213.137:/app/telegram-bot/webhook/dashboard.py
```

- [ ] **5.4 Обновить изменённые файлы на сервере**

```bash
for f in \
  "database/models.py" \
  "database/crud.py" \
  "database/__init__.py" \
  "telegram-bot/handlers/commands.py" \
  "telegram-bot/webhook/apple_health.py" \
  "telegram-bot/bot.py"; do
  /opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' scp \
    "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine/$f" \
    "root@116.203.213.137:/app/$f"
done
```

- [ ] **5.5 Перезапустить контейнер бота**

```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker restart healthvault_bot && sleep 3 && docker logs healthvault_bot --tail 20"
```

Ожидаемый вывод: `HealthVault Tracker v1.2` + `✅ Бот успешно запущен`

- [ ] **5.6 Проверить endpoint**

Сначала сгенерировать токен для Александра (user_id 895655):
```bash
/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
   \"UPDATE users SET share_token = gen_random_uuid()::text WHERE telegram_id = 895655 AND share_token IS NULL RETURNING share_token;\""
```

Получить токен и проверить URL:
```bash
TOKEN=$(/opt/homebrew/bin/sshpass -p 'SERVER_PASSWORD_REDACTED' ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec healthvault_postgres psql -U healthvault -d healthvault -t -c \
   \"SELECT share_token FROM users WHERE telegram_id = 895655;\"" | tr -d ' \n')
echo "URL: https://health.orangegate.cc/mc/$TOKEN"
curl -s -o /dev/null -w "%{http_code}" "https://health.orangegate.cc/mc/$TOKEN"
```

Ожидаемый вывод: `200`

- [ ] **5.7 Открыть в браузере**

```bash
open "https://health.orangegate.cc/mc/$TOKEN"
```

- [ ] **5.8 Проверить бот-команду через Telegram**

Написать боту `/share` — должна прийти ссылка. Открыть ссылку — должен открыться дашборд.

---

## Проверка (Definition of Done)

- [ ] `GET /mc/{known_token}` возвращает HTTP 200 с HTML-страницей
- [ ] `GET /mc/invalid-token` возвращает HTTP 404
- [ ] Бот отвечает на `/share` ссылкой вида `health.orangegate.cc/mc/{uuid}`
- [ ] `/share reset` генерирует новый UUID, старая ссылка даёт 404
- [ ] Дашборд показывает реальные данные Александра (вес, питание, сон)
- [ ] Страница открывается без логина — чистый браузер, инкогнито
