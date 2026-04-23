"""
HealthVault Share Dashboard Generator
Читает данные пользователя из PostgreSQL → возвращает HTML-строку.
Дизайн: тёмный Mission Control, зелёный #00ff9d акцент.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session


# ── Data aggregation ──────────────────────────────────────────────────────────


def _collect_user_data(db: Session, user_id: int) -> dict:
    """Агрегирует данные пользователя из БД за всё время."""
    from database.crud import (
        get_activities_by_period,
        get_nutrition_logs_by_period,
        get_supplements_by_period,
        get_user_by_telegram_id,
        get_weights_by_period,
    )
    from database.models import UserSettings

    user = get_user_by_telegram_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    display_name = user.first_name or user.username or f"User {user_id}"
    today = date.today()
    project_start = date(2026, 1, 6)
    registered = user.registered_at.date() if user.registered_at else project_start
    start = max(project_start, registered)
    total_days = (today - start).days + 1

    # ── Weight (get_weights_by_period expects datetime) ──
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())
    weights = get_weights_by_period(db, user_id, start_dt, end_dt)
    weight_series: dict[str, float] = {}
    fat_series: dict[str, float] = {}
    for w in weights:
        d = w.measured_at.date().isoformat()
        weight_series[d] = round(w.weight, 2)
        if w.body_fat is not None:
            fat_series[d] = round(w.body_fat, 1)

    # ── Nutrition ──
    nutrition_logs = get_nutrition_logs_by_period(db, user_id, start, today)
    kcal_series: dict[str, int] = {}
    prot_series: dict[str, float] = {}
    for log in nutrition_logs:
        d = log.date.isoformat()
        totals = log.totals or {}
        kcal_series[d] = kcal_series.get(d, 0) + int(totals.get("calories") or 0)
        prot_series[d] = round(prot_series.get(d, 0.0) + float(totals.get("protein") or 0), 1)
    kcal_series = {k: v for k, v in kcal_series.items() if v > 0}
    prot_series = {k: v for k, v in prot_series.items() if v > 0}

    # ── Supplements ──
    supps = get_supplements_by_period(db, user_id, start, today)
    supp_days = sorted({s.date.isoformat() for s in supps})

    # ── Activity (sleep, steps, HRV from raw_data) ──
    activities = get_activities_by_period(db, user_id, start, today)
    sleep_series: dict[str, float] = {}
    steps_series: dict[str, int] = {}
    hrv_series: dict[str, int] = {}
    stress_series: dict[str, int] = {}
    bb_series: dict[str, int] = {}
    rhr_series: dict[str, int] = {}
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
        if a.raw_data:
            bb = a.raw_data.get("body_battery_max")
            if bb:
                bb_series[d] = int(bb)

    # ── Weight stats ──
    stats_weight: dict = {}
    if weight_series:
        first_date = min(weight_series)
        last_date = max(weight_series)
        stats_weight = {
            "first": weight_series[first_date],
            "last": weight_series[last_date],
            "min": min(weight_series.values()),
            "max": max(weight_series.values()),
            "delta": round(weight_series[last_date] - weight_series[first_date], 2),
        }

    # ── Target weight ──
    settings = db.query(UserSettings).filter_by(user_id=user_id).first()
    target_weight = (settings.target_weight_kg if settings else None) or user.target_weight_kg

    return {
        "meta": {
            "user_id": user_id,
            "display_name": display_name,
            "today": today.isoformat(),
            "start": start.isoformat(),
            "total_days": total_days,
            "generated_at": datetime.now().isoformat(),
            "target_weight_kg": target_weight,
        },
        "weight": weight_series,
        "fat": fat_series,
        "stats_weight": stats_weight,
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
    """Главная точка входа: данные из БД → HTML-строка."""
    data = _collect_user_data(db, user_id)
    return _render_html(data)


def _avg(d: dict) -> float:
    return round(sum(d.values()) / len(d), 1) if d else 0.0


def _render_html(data: dict) -> str:
    meta = data["meta"]
    sw = data["stats_weight"]
    display_name = meta["display_name"]
    today_str = meta["today"]
    start_str = meta["start"]
    total_days = meta["total_days"]
    generated_at = meta["generated_at"][:16].replace("T", " ")
    target_w = meta.get("target_weight_kg")

    sleep_avg = _avg(data["sleep_h"])
    hrv_avg = int(_avg(data["hrv"])) if data["hrv"] else 0
    stress_avg = int(_avg(data["stress"])) if data["stress"] else 0
    rhr_avg = int(_avg(data["rhr"])) if data["rhr"] else 0
    steps_avg = int(_avg(data["steps"])) if data["steps"] else 0
    bb_avg = int(_avg(data["body_battery"])) if data["body_battery"] else 0
    kcal_avg = int(_avg(data["kcal"])) if data["kcal"] else 0
    prot_avg = _avg(data["prot"]) if data["prot"] else 0.0
    supp_days_n = len(data["supp_days"])

    weight_last = sw.get("last", "—")
    weight_delta = sw.get("delta", 0.0)
    fat_vals = list(data["fat"].values())
    fat_last = round(fat_vals[-1], 1) if fat_vals else None

    # Embed data for JS
    js_data = json.dumps(
        {
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
        },
        ensure_ascii=False,
    )

    # Delta pill
    delta_sign = "↓" if weight_delta < 0 else "↑"
    delta_color = "g" if weight_delta < 0 else "r"
    delta_pill = (
        f'<span class="delta-pill {delta_color}">{delta_sign} {abs(weight_delta)} кг</span>' if weight_delta else ""
    )

    # ── Stream cards ──────────────────────────────────────────────────────────
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
    if supp_days_n > 0:
        streams.append(("💊", "Добавки", supp_days_n, "дней", None, "#a78bfa"))

    stream_cards_html = ""
    for emoji, name, val, unit, key, color in streams:
        spark = f'<canvas id="spark_{key}" class="spark"></canvas>' if key else ""
        stream_cards_html += f"""
      <div class="stream">
        <div class="name">{emoji} {name}</div>
        <div class="val-row"><span class="val">{val}</span><span class="unit">{unit}</span></div>
        {spark}
      </div>"""

    grid_cols = min(len(streams), 6) if streams else 3

    stream_section = ""
    if streams:
        stream_section = f"""
<div class="section-title">ПОТОКИ ДАННЫХ <span class="hint">с {start_str}</span></div>
<div class="streams-grid" style="grid-template-columns: repeat({grid_cols}, minmax(0,1fr));">
  {stream_cards_html}
</div>"""

    # ── Weight section ────────────────────────────────────────────────────────
    weight_section = ""
    if data["weight"]:
        fat_line = f'<div class="sub">Жир: {fat_last}%</div>' if fat_last is not None else ""
        target_line = (
            f'<div class="sub">цель {target_w} кг · T−<span id="cd-days">—</span> дн</div>' if target_w else ""
        )
        weight_section = f"""
<div class="section-title">ВЕС <span class="hint">с {start_str}</span></div>
<div class="card">
  <div style="font-size:42px;font-weight:800;line-height:1;">
    {weight_last} <span style="font-size:18px;color:var(--muted)">кг</span> {delta_pill}
  </div>
  {fat_line}
  {target_line}
  <div class="chart-wrap" style="height:200px;margin-top:16px;"><canvas id="weightChart"></canvas></div>
</div>"""

    # ── Nutrition section ─────────────────────────────────────────────────────
    nutrition_section = ""
    if data["kcal"]:
        nutrition_section = f"""
<div class="section-title">ПИТАНИЕ <span class="hint">среднее {kcal_avg} ккал · {prot_avg} г белка</span></div>
<div class="card">
  <div class="chart-wrap" style="height:180px;"><canvas id="nutritionChart"></canvas></div>
</div>"""

    # ── Sparkline JS ─────────────────────────────────────────────────────────
    spark_keys = [k for _, _, _, _, k, _ in streams if k]
    spark_colors = {k: c for _, _, _, _, k, c in streams if k}
    spark_js = ""
    for key in spark_keys:
        color = spark_colors.get(key, "#00ff9d")
        spark_js += f"""
  (function() {{
    const el = document.getElementById('spark_{key}');
    if (!el || !D['{key}'] || !Object.keys(D['{key}']).length) return;
    new Chart(el, {{
      type: 'line',
      data: {{ datasets: [{{ data: toPoints(D['{key}']),
               borderColor: '{color}', borderWidth: 1.5, pointRadius: 0, tension: 0.3,
               fill: true, backgroundColor: '{color}18' }}] }},
      options: {{
        animation: false, responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
        scales: {{ x: {{ type: 'time', display: false }}, y: {{ display: false }} }}
      }}
    }});
  }})();"""

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
  --bg:#0a0e17; --card:#111827; --border:#1f2940;
  --g:#00ff9d; --r:#ff3b6d; --y:#fbbf24; --b:#3b82f6; --p:#a78bfa;
  --text:#e8eef7; --muted:#7a879f;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);
  font-family:'SF Pro Display','Inter',-apple-system,sans-serif;
  font-size:14px;line-height:1.4;padding:20px;
  background-image:
    radial-gradient(circle at 20% 0%,rgba(0,255,157,.03) 0%,transparent 50%),
    radial-gradient(circle at 80% 100%,rgba(168,85,247,.03) 0%,transparent 50%);
}}
.topbar{{display:flex;justify-content:space-between;align-items:center;
  padding:14px 20px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;margin-bottom:20px;position:relative;overflow:hidden;}}
.topbar::before{{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,transparent 0%,rgba(0,255,157,.06) 50%,transparent 100%);
  animation:scan 8s linear infinite;}}
@keyframes scan{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(100%)}}}}
.logo{{font-size:20px;font-weight:800;letter-spacing:-.5px;}}
.logo .accent{{color:var(--g);}}
.meta-info{{font-size:11px;color:var(--muted);text-align:right;line-height:1.8;}}
.dot{{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--g);box-shadow:0 0 10px var(--g);animation:pulse 2s ease-in-out infinite;}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;
  position:relative;overflow:hidden;}}
.section-title{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:2px;
  color:var(--text);margin:28px 0 12px;display:flex;align-items:center;gap:10px;}}
.section-title::before{{content:'';width:4px;height:14px;background:var(--g);border-radius:2px;}}
.section-title .hint{{font-size:10px;font-weight:400;color:var(--muted);
  text-transform:none;letter-spacing:.3px;margin-left:8px;}}
.streams-grid{{display:grid;gap:14px;}}
.stream{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;}}
.stream .name{{font-size:10px;color:var(--muted);text-transform:uppercase;
  letter-spacing:1px;margin-bottom:4px;}}
.stream .val-row{{display:flex;align-items:baseline;gap:4px;}}
.stream .val{{font-size:22px;font-weight:700;line-height:1.1;}}
.stream .unit{{font-size:11px;color:var(--muted);font-weight:400;}}
.stream .spark{{height:28px;margin-top:6px;}}
.chart-wrap{{position:relative;}}
.delta-pill{{display:inline-block;font-size:12px;font-weight:600;padding:3px 9px;
  border-radius:20px;margin-left:8px;vertical-align:middle;}}
.delta-pill.g{{background:rgba(0,255,157,.12);color:var(--g);}}
.delta-pill.r{{background:rgba(255,59,109,.12);color:var(--r);}}
.sub{{font-size:12px;color:var(--muted);margin-top:6px;}}
footer{{margin-top:40px;text-align:center;font-size:11px;color:var(--muted);opacity:.5;}}
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
Chart.defaults.color = '#7a879f';
Chart.defaults.font.family = "'SF Pro Display','Inter',sans-serif";
Chart.defaults.font.size = 10;
Chart.defaults.borderColor = '#1f2940';

function toPoints(obj) {{
  return Object.entries(obj).sort().map(([x,y]) => ({{x, y}}));
}}

{spark_js}

// Weight chart
const weightEl = document.getElementById('weightChart');
if (weightEl && Object.keys(D.weight).length) {{
  const datasets = [{{
    label:'Вес, кг', data:toPoints(D.weight),
    borderColor:'#00ff9d', borderWidth:2, pointRadius:0, tension:0.3, yAxisID:'yW',
    fill:true, backgroundColor:'rgba(0,255,157,.06)',
  }}];
  if (Object.keys(D.fat).length) {{
    datasets.push({{
      label:'Жир, %', data:toPoints(D.fat),
      borderColor:'#fbbf24', borderWidth:1.5, pointRadius:0, tension:0.3,
      yAxisID:'yF', borderDash:[4,3],
    }});
  }}
  new Chart(weightEl, {{
    type:'line', data:{{datasets}},
    options:{{
      animation:false, responsive:true, maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{
        legend:{{display:true,position:'top',labels:{{color:'#7a879f',boxWidth:12,font:{{size:10}}}}}},
        tooltip:{{backgroundColor:'#0a0e17',borderColor:'#1f2940',borderWidth:1}},
      }},
      scales:{{
        x:{{type:'time',time:{{unit:'week',displayFormats:{{week:'dd.MM'}}}},grid:{{display:false}}}},
        yW:{{position:'left',grid:{{color:'#1f2940'}}}},
        yF:{{position:'right',grid:{{display:false}}}},
      }}
    }}
  }});

  // T-minus countdown to target weight
  const cdEl = document.getElementById('cd-days');
  if (cdEl && D.meta.target_weight_kg && D.stats_weight.delta < 0) {{
    const ratePerDay = D.stats_weight.delta / D.meta.total_days;
    const remaining = D.meta.target_weight_kg - D.stats_weight.last;
    const daysLeft = ratePerDay < 0 ? Math.round(remaining / ratePerDay) : null;
    cdEl.textContent = (daysLeft && daysLeft > 0) ? daysLeft : '—';
  }}
}}

// Nutrition chart
const nutEl = document.getElementById('nutritionChart');
if (nutEl && Object.keys(D.kcal).length) {{
  new Chart(nutEl, {{
    type:'bar',
    data:{{datasets:[{{
      label:'Ккал', data:toPoints(D.kcal),
      backgroundColor:'rgba(59,130,246,.6)', borderWidth:0, borderRadius:2,
    }}]}},
    options:{{
      animation:false, responsive:true, maintainAspectRatio:false,
      plugins:{{
        legend:{{display:false}},
        tooltip:{{backgroundColor:'#0a0e17',borderColor:'#1f2940',borderWidth:1}},
      }},
      scales:{{
        x:{{type:'time',time:{{unit:'week',displayFormats:{{week:'dd.MM'}}}},grid:{{display:false}}}},
        y:{{grid:{{color:'#1f2940'}}}},
      }}
    }}
  }});
}}
</script>
</body>
</html>"""
