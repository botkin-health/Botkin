"""Admin dashboard — `/admin/` page + API endpoints.

HTTP Basic Auth: username `admin`, password from env ADMIN_PASSWORD.
Provides:
- Users list with data volumes and actions
- Server disk/db usage
- Backup management (list + create)

MVP scope. v1/v2 features are tracked in project todo.md.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic(auto_error=False)


BACKUPS_DIR = Path("/app/backups")  # mounted from /opt/backups on host


# ─── Auth ──────────────────────────────────────────────────────────────────


def _check_auth(creds: Optional[HTTPBasicCredentials]) -> None:
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_pass = os.getenv("ADMIN_PASSWORD", "")
    if not expected_pass:
        # Safety: if ADMIN_PASSWORD env not set, refuse all admin access
        raise HTTPException(status_code=503, detail="Admin not configured")
    if not creds or not (
        secrets.compare_digest(creds.username.encode(), expected_user.encode())
        and secrets.compare_digest(creds.password.encode(), expected_pass.encode())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth required",
            headers={"WWW-Authenticate": 'Basic realm="Botkin Admin"'},
        )


def admin_auth(creds: Optional[HTTPBasicCredentials] = Depends(security)) -> str:
    _check_auth(creds)
    return creds.username  # type: ignore


# ─── HTML page ─────────────────────────────────────────────────────────────

ADMIN_HTML = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><title>Botkin · Admin</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0a0e17;--bg2:#0f1420;--card:#141a28;--bd:#1f2940;--fg:#e8eef7;--mu:#7a879f;--g:#00ff9d;--y:#ffb800;--r:#ff3b6d;--b:#3b82f6;--p:#a855f7}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,'SF Pro Text','Inter',sans-serif;padding:24px;min-height:100vh;
 background-image:radial-gradient(circle at 20% 0%,rgba(0,255,157,.04) 0%,transparent 50%),radial-gradient(circle at 80% 100%,rgba(168,85,247,.04) 0%,transparent 50%)}
.mono{font-family:'SF Mono','JetBrains Mono',Menlo,monospace}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--bd)}
h1{font-size:20px;font-weight:600;letter-spacing:.5px}
h1 .sub{color:var(--mu);font-weight:400;margin-left:12px;font-size:13px}
section{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:20px;margin-bottom:20px}
section h2{font-size:15px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:500;background:var(--bd);color:var(--mu);margin-left:6px}
.badge.g{background:rgba(0,255,157,.12);color:var(--g)}
.badge.y{background:rgba(255,184,0,.12);color:var(--y)}
.badge.r{background:rgba(255,59,109,.12);color:var(--r)}
.badge.b{background:rgba(59,130,246,.12);color:var(--b)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--bd);vertical-align:middle}
th{font-weight:500;color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.5px;background:rgba(255,255,255,.02)}
tr:hover td{background:rgba(255,255,255,.02)}
.muted{color:var(--mu)}.dim{color:#4a556b}
button,select{font:inherit;background:var(--bg2);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:6px 10px;cursor:pointer;transition:.15s}
button:hover,select:hover{border-color:var(--b);background:var(--card)}
button.primary{background:var(--b);border-color:var(--b);color:#fff;font-weight:500}
button.primary:hover{background:#2563eb}
button.danger{color:var(--r);border-color:rgba(255,59,109,.4)}
button.danger:hover{background:rgba(255,59,109,.1)}
button.ok{color:var(--g);border-color:rgba(0,255,157,.3)}
.actions{display:flex;gap:6px;flex-wrap:wrap}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--bg2);padding:14px;border-radius:8px;border:1px solid var(--bd)}
.kpi .l{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.kpi .v{font-size:22px;font-weight:600}
.kpi .n{color:var(--mu);font-size:12px;margin-top:2px}
.bar{height:6px;background:var(--bd);border-radius:3px;overflow:hidden;margin-top:6px}
.bar>div{height:100%;background:var(--b);transition:width .3s}
.bar.warn>div{background:var(--y)}.bar.crit>div{background:var(--r)}
.flex{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--bd);border-top-color:var(--b);border-radius:50%;animation:s 0.8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.toast{position:fixed;bottom:24px;right:24px;background:var(--card);border:1px solid var(--bd);padding:12px 16px;border-radius:8px;max-width:320px}
.toast.ok{border-color:var(--g)}.toast.err{border-color:var(--r)}
.placeholder{padding:24px;text-align:center;color:var(--mu);background:var(--bg2);border:1px dashed var(--bd);border-radius:8px}
input.editable{background:transparent;border:1px solid transparent;color:var(--fg);padding:4px 6px;border-radius:4px;font-family:inherit;font-size:inherit;width:100%}
input.editable:hover{border-color:var(--bd)}
input.editable:focus{border-color:var(--b);outline:none;background:var(--bg2)}
.cohort-pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500;text-transform:uppercase}
.c-owner{background:rgba(168,85,247,.15);color:var(--p)}
.c-family{background:rgba(0,255,157,.12);color:var(--g)}
.c-early_user{background:rgba(255,184,0,.12);color:var(--y)}
.c-external{background:var(--bd);color:var(--mu)}
.kb-pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500;border:none;cursor:pointer}
.k-shared{background:rgba(0,255,157,.12);color:var(--g)}
.k-private{background:rgba(59,130,246,.15);color:var(--b)}
.k-none{background:var(--bd);color:var(--mu)}
.tools{display:flex;gap:8px;align-items:center}
</style></head><body>

<header>
  <h1>Botkin Admin <span class="sub mono" id="now"></span></h1>
  <div class="tools">
    <button onclick="loadAll()">↻ Обновить</button>
  </div>
</header>

<section>
  <h2>👥 Пользователи <span class="badge" id="users-count">…</span></h2>
  <div class="kpi-row" id="users-kpi"></div>
  <div style="overflow-x:auto"><table id="users-table">
    <thead><tr>
      <th>Имя</th><th>Telegram</th><th title="Telegram user_id, он же primary key в нашей БД">Telegram ID</th>
      <th>Cohort</th><th>Возраст</th><th>Зарегистрирован</th><th>Активен</th>
      <th>Meals 7д/всего</th><th>Supps 7д/всего</th>
      <th title="Health Knowledge Base — папка с медданными, профилем и анализами">KB</th>
      <th>Действия</th>
    </tr></thead>
    <tbody><tr><td colspan="11" class="placeholder">Загрузка…</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>💾 Сервер и Postgres</h2>
  <div id="server-data"><div class="placeholder">Загрузка…</div></div>
</section>

<section>
  <h2>🗄 Бэкапы <span class="badge" id="backups-count">…</span></h2>
  <div class="flex" style="margin-bottom:12px">
    <button class="primary" onclick="makeBackup()" id="bkp-btn">Сделать бэкап сейчас</button>
    <span class="muted">Хранилище: <span class="mono">/opt/backups</span> на сервере</span>
  </div>
  <div id="backups-data"><div class="placeholder">Загрузка…</div></div>
</section>

<section>
  <h2>💰 Расходы на нейронки</h2>
  <div class="muted" style="margin-bottom:8px">
    Период:
    <select id="llm-window" onchange="loadLLM()">
      <option value="1">сегодня</option>
      <option value="7" selected>7 дней</option>
      <option value="30">30 дней</option>
      <option value="90">90 дней</option>
    </select>
    <span id="llm-totals" style="margin-left:14px"></span>
  </div>
  <table style="font-size:13px">
    <thead><tr>
      <th>Назначение</th><th>Вызовов</th><th>Input · Output</th><th>Cache R/W</th><th>USD</th>
    </tr></thead>
    <tbody id="llm-by-purpose"></tbody>
  </table>
  <details style="margin-top:8px">
    <summary class="muted">📊 По дням</summary>
    <table style="font-size:12px; margin-top:8px">
      <thead><tr><th>День</th><th>food_text</th><th>food_photo</th><th>agent_chat</th><th>Σ USD</th></tr></thead>
      <tbody id="llm-by-day"></tbody>
    </table>
  </details>
  <details style="margin-top:8px">
    <summary class="muted">👥 По юзерам</summary>
    <table style="font-size:12px; margin-top:8px">
      <thead><tr><th>User ID</th><th>Имя</th><th>Вызовов</th><th>USD</th></tr></thead>
      <tbody id="llm-by-user"></tbody>
    </table>
  </details>
</section>

<section>
  <h2>🤖 Здоровье бота <span class="badge y">v1 — TODO</span></h2>
  <div class="placeholder">
    Uptime, ошибки, webhook latency — добавим в v1.<br>
    Сейчас: <span class="mono">ssh берлин && docker compose logs --tail=200 bot</span>
  </div>
</section>

<div id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
function fmt(n){ if(n===null||n===undefined)return '—'; if(typeof n!=='number')return n; if(n>=1024*1024*1024)return(n/1024/1024/1024).toFixed(2)+' ГБ'; if(n>=1024*1024)return(n/1024/1024).toFixed(1)+' МБ'; if(n>=1024)return(n/1024).toFixed(1)+' КБ'; return n+' Б' }
function fmtDate(s){ if(!s)return '—'; const d=new Date(s); const now=new Date(); const diff=(now-d)/1000; if(diff<60)return Math.round(diff)+'с назад'; if(diff<3600)return Math.round(diff/60)+'м назад'; if(diff<86400)return Math.round(diff/3600)+'ч назад'; if(diff<86400*30)return Math.round(diff/86400)+'д назад'; return d.toISOString().slice(0,10) }
function toast(msg, kind){ const t=$('toast'); t.innerHTML='<div class="toast '+(kind||'ok')+'">'+msg+'</div>'; setTimeout(()=>{t.innerHTML=''}, 3500) }
async function api(path, opts){ const r=await fetch(path, opts); if(!r.ok) throw new Error(await r.text()); return r.json() }

async function loadUsers(){
  try{
    const d = await api('/admin/api/users');
    $('users-count').textContent = d.count;
    const stat = d.stats;
    $('users-kpi').innerHTML = `
      <div class="kpi"><div class="l">Всего</div><div class="v">${stat.total}</div></div>
      <div class="kpi"><div class="l">Активные (7 дней)</div><div class="v">${stat.active_7d}</div><div class="n">из ${stat.total}</div></div>
      <div class="kpi"><div class="l">Family</div><div class="v">${stat.cohorts.family||0}</div></div>
      <div class="kpi"><div class="l">Early users</div><div class="v">${stat.cohorts.early_user||0}</div></div>
      <div class="kpi"><div class="l">External</div><div class="v">${stat.cohorts.external||0}</div></div>
      <div class="kpi"><div class="l">Заблокированы</div><div class="v">${stat.blocked}</div></div>`;
    const KB_OPTS = [
      ['shared',  '🟢 Shared'],
      ['private', '🔒 Private'],
      ['none',    '⚪ None'],
    ];
    const rows = d.users.map(u => {
      const cohorts = ['owner','family','early_user','external'].map(c =>
        `<option value="${c}"${c===u.cohort?' selected':''}>${c}</option>`).join('');
      const kbCurrent = u.kb_status || 'none';
      const kbOpts = KB_OPTS.map(([v,lbl]) =>
        `<option value="${v}"${v===kbCurrent?' selected':''}>${lbl}</option>`).join('');
      const kbCls = 'kb-pill k-' + kbCurrent;
      const blockBtn = u.is_active
        ? `<button class="danger" onclick="toggleActive(${u.telegram_id}, false)">блок</button>`
        : `<button class="ok" onclick="toggleActive(${u.telegram_id}, true)">разблок</button>`;
      const sx = (u.sex||'').toLowerCase();
      const sexEmoji = (sx==='male'||sx==='m') ? '♂' : ((sx==='female'||sx==='f') ? '♀' : '');
      const ageStr = u.age!==null ? `${u.age}л ${sexEmoji}` : '<span class="dim">—</span>';
      return `<tr>
        <td>${u.first_name||''} ${u.last_name||''}</td>
        <td class="mono muted">@${u.username||'—'}</td>
        <td class="mono dim">${u.telegram_id}</td>
        <td><select onchange="changeCohort(${u.telegram_id}, this.value)" class="cohort-pill c-${u.cohort}">${cohorts}</select></td>
        <td>${ageStr}</td>
        <td class="muted">${fmtDate(u.registered_at)}</td>
        <td class="muted">${fmtDate(u.last_active)}</td>
        <td><span class="${u.meals_7d?'':'dim'}">${u.meals_7d}</span> / <span class="muted">${u.meals_total}</span></td>
        <td><span class="${u.supps_7d?'':'dim'}">${u.supps_7d}</span> / <span class="muted">${u.supps_total}</span></td>
        <td><select onchange="changeKB(${u.telegram_id}, this.value)" class="${kbCls}">${kbOpts}</select></td>
        <td class="actions">${blockBtn}</td>
      </tr>`;
    }).join('');
    $('users-table').querySelector('tbody').innerHTML = rows || '<tr><td colspan="11" class="placeholder">Нет пользователей</td></tr>';
  } catch(e){ toast('Ошибка загрузки юзеров: '+e.message, 'err') }
}

async function loadServer(){
  try{
    const d = await api('/admin/api/server');
    const dp = d.disk;
    const dbsize = d.db.total_size;
    const tableHTML = (d.db.top_tables||[]).map(t =>
      `<tr><td class="mono">${t.name}</td><td>${t.size_pretty}</td><td class="muted">${t.rows} строк</td></tr>`).join('');
    $('server-data').innerHTML = `
      <div class="kpi-row">
        <div class="kpi"><div class="l">Postgres всего</div><div class="v">${dbsize}</div></div>
        <div class="kpi"><div class="l">Диск занято</div><div class="v">${dp.used_pretty}<span class="muted" style="font-size:13px"> / ${dp.total_pretty}</span></div>
          <div class="bar ${dp.percent>80?'crit':dp.percent>60?'warn':''}"><div style="width:${dp.percent}%"></div></div>
          <div class="n">${dp.percent}%</div></div>
        <div class="kpi"><div class="l">/opt/healthvault</div><div class="v">${d.paths.healthvault}</div></div>
        <div class="kpi"><div class="l">/opt/backups</div><div class="v">${d.paths.backups}</div></div>
      </div>
      <h3 style="font-size:13px;font-weight:500;color:var(--mu);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px">Топ таблиц</h3>
      <table><thead><tr><th>Таблица</th><th>Размер</th><th>Строк</th></tr></thead><tbody>${tableHTML}</tbody></table>`;
  } catch(e){ $('server-data').innerHTML = '<div class="placeholder">Ошибка: '+e.message+'</div>' }
}

async function loadBackups(){
  try{
    const d = await api('/admin/api/backups');
    $('backups-count').textContent = d.count;
    if(!d.backups.length){
      $('backups-data').innerHTML = '<div class="placeholder">Бэкапов пока нет. Нажми «Сделать бэкап сейчас».</div>';
      return;
    }
    const rows = d.backups.map(b =>
      `<tr><td class="mono">${b.name}</td><td>${b.size_pretty}</td><td class="muted">${fmtDate(b.created)}</td></tr>`).join('');
    $('backups-data').innerHTML = `<table><thead><tr><th>Файл</th><th>Размер</th><th>Создан</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch(e){ $('backups-data').innerHTML = '<div class="placeholder">Ошибка: '+e.message+'</div>' }
}

async function makeBackup(){
  const btn=$('bkp-btn'); btn.disabled=true; btn.innerHTML='<span class="spinner"></span> Создаём бэкап…';
  try{
    const d = await api('/admin/api/backups', {method:'POST'});
    toast('✓ Бэкап создан: '+d.name+' ('+d.size_pretty+')');
    loadBackups();
  } catch(e){ toast('Ошибка: '+e.message, 'err') }
  finally{ btn.disabled=false; btn.textContent='Сделать бэкап сейчас' }
}

async function toggleActive(tid, active){
  try{
    await api('/admin/api/users/'+tid+'/active', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({is_active: active})});
    toast(active ? '✓ Разблокирован' : '✓ Заблокирован');
    loadUsers();
  } catch(e){ toast('Ошибка: '+e.message, 'err') }
}

async function changeCohort(tid, cohort){
  try{
    await api('/admin/api/users/'+tid+'/cohort', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cohort})});
    toast('✓ Cohort → '+cohort);
    loadUsers();
  } catch(e){ toast('Ошибка: '+e.message, 'err') }
}

async function changeKB(tid, kb){
  try{
    await api('/admin/api/users/'+tid+'/kb', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kb_status: kb})});
    toast('✓ KB → '+kb);
    loadUsers();
  } catch(e){ toast('Ошибка: '+e.message, 'err') }
}

async function loadLLM(){
  try{
    const days = document.getElementById('llm-window').value;
    const d = await api('/admin/api/llm_usage?days=' + days);
    document.getElementById('llm-totals').innerHTML =
      '<b>Σ ' + d.totals.calls + '</b> вызовов · ' +
      '<b>$' + d.totals.cost_usd.toFixed(4) + '</b> · ' +
      d.totals.input_tokens.toLocaleString() + ' in / ' +
      d.totals.output_tokens.toLocaleString() + ' out';
    document.getElementById('llm-by-purpose').innerHTML = d.by_purpose.map(r =>
      '<tr><td><span class="mono">' + r.purpose + '</span></td>' +
      '<td>' + r.calls + '</td>' +
      '<td>' + r.input_tokens.toLocaleString() + ' · ' + r.output_tokens.toLocaleString() + '</td>' +
      '<td>' + r.cache_read_tokens.toLocaleString() + ' / ' + r.cache_creation_tokens.toLocaleString() + '</td>' +
      '<td><b>$' + r.cost_usd.toFixed(4) + '</b></td></tr>'
    ).join('');
    document.getElementById('llm-by-day').innerHTML = d.by_day.map(r =>
      '<tr><td>' + r.day + '</td>' +
      '<td>$' + (r.food_text_usd||0).toFixed(4) + '</td>' +
      '<td>$' + (r.food_photo_usd||0).toFixed(4) + '</td>' +
      '<td>$' + (r.agent_chat_usd||0).toFixed(4) + '</td>' +
      '<td><b>$' + r.total_usd.toFixed(4) + '</b></td></tr>'
    ).join('');
    document.getElementById('llm-by-user').innerHTML = d.by_user.map(r =>
      '<tr><td class="mono">' + (r.user_id || '—') + '</td>' +
      '<td>' + (r.first_name || '') + '</td>' +
      '<td>' + r.calls + '</td>' +
      '<td><b>$' + r.cost_usd.toFixed(4) + '</b></td></tr>'
    ).join('');
  } catch(e){ toast('Ошибка LLM: '+e.message, 'err') }
}

function loadAll(){ loadUsers(); loadServer(); loadBackups(); loadLLM() }
function tick(){ $('now').textContent = new Date().toLocaleString('ru-RU') }

tick(); setInterval(tick, 1000);
loadAll();
setInterval(loadAll, 60000);  // refresh every minute
</script>
</body></html>
"""


@router.get("/", response_class=HTMLResponse)
async def admin_index(_: str = Depends(admin_auth)) -> HTMLResponse:
    return HTMLResponse(content=ADMIN_HTML)


# ─── API: Users ────────────────────────────────────────────────────────────


@router.get("/api/users")
async def api_users(_: str = Depends(admin_auth)) -> JSONResponse:
    db = SessionLocal()
    try:
        # Aggregate metrics in raw SQL for performance
        sql = text("""
            SELECT
              u.telegram_id, u.username, u.first_name, u.last_name,
              u.is_active, u.cohort, u.timezone, u.registered_at, u.last_active,
              u.birth_date, u.sex, u.kb_status,
              (SELECT count(*) FROM nutrition_log WHERE user_id = u.telegram_id) AS meals_total,
              (SELECT count(*) FROM nutrition_log WHERE user_id = u.telegram_id AND date >= (CURRENT_DATE - INTERVAL '7 days')) AS meals_7d,
              (SELECT count(*) FROM supplements_log WHERE user_id = u.telegram_id) AS supps_total,
              (SELECT count(*) FROM supplements_log WHERE user_id = u.telegram_id AND date >= (CURRENT_DATE - INTERVAL '7 days')) AS supps_7d
            FROM users u
            ORDER BY u.last_active DESC NULLS LAST, u.registered_at DESC
        """)
        rows = db.execute(sql).fetchall()

        today = date.today()
        users = []
        cohort_counts = {}
        active_7d = 0
        blocked = 0
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        for r in rows:
            age = None
            if r.birth_date:
                age = (
                    today.year - r.birth_date.year - ((today.month, today.day) < (r.birth_date.month, r.birth_date.day))
                )
            users.append(
                {
                    "telegram_id": r.telegram_id,
                    "username": r.username,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "is_active": r.is_active,
                    "cohort": r.cohort,
                    "timezone": r.timezone,
                    "registered_at": r.registered_at.isoformat() if r.registered_at else None,
                    "last_active": r.last_active.isoformat() if r.last_active else None,
                    "age": age,
                    "sex": r.sex,
                    "meals_total": r.meals_total,
                    "meals_7d": r.meals_7d,
                    "supps_total": r.supps_total,
                    "supps_7d": r.supps_7d,
                    "kb_status": r.kb_status,  # 'shared' / 'private' / 'none' / null
                }
            )
            cohort_counts[r.cohort] = cohort_counts.get(r.cohort, 0) + 1
            if r.last_active and r.last_active >= seven_days_ago:
                active_7d += 1
            if not r.is_active:
                blocked += 1

        return JSONResponse(
            {
                "count": len(users),
                "users": users,
                "stats": {
                    "total": len(users),
                    "active_7d": active_7d,
                    "blocked": blocked,
                    "cohorts": cohort_counts,
                },
            }
        )
    finally:
        db.close()


@router.post("/api/users/{tg_id}/active")
async def api_user_active(tg_id: int, request: Request, _: str = Depends(admin_auth)) -> JSONResponse:
    body = await request.json()
    is_active = bool(body.get("is_active"))
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(telegram_id=tg_id).first()
        if not u:
            raise HTTPException(404, "User not found")
        u.is_active = is_active
        db.commit()
        logger.info(f"[admin] User {tg_id} is_active → {is_active}")
        return JSONResponse({"ok": True, "is_active": is_active})
    finally:
        db.close()


@router.post("/api/users/{tg_id}/cohort")
async def api_user_cohort(tg_id: int, request: Request, _: str = Depends(admin_auth)) -> JSONResponse:
    body = await request.json()
    cohort = body.get("cohort")
    if cohort not in ("owner", "family", "early_user", "external"):
        raise HTTPException(400, "Invalid cohort")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(telegram_id=tg_id).first()
        if not u:
            raise HTTPException(404, "User not found")
        u.cohort = cohort
        db.commit()
        logger.info(f"[admin] User {tg_id} cohort → {cohort}")
        return JSONResponse({"ok": True, "cohort": cohort})
    finally:
        db.close()


@router.post("/api/users/{tg_id}/kb")
async def api_user_kb(tg_id: int, request: Request, _: str = Depends(admin_auth)) -> JSONResponse:
    """Update Health Knowledge Base attachment status.

    - 'shared'  — KB folder lives in the shared family Google Drive
                  (`~/Library/CloudStorage/.../HealthVault/{Имя} — Здоровье/`)
    - 'private' — User keeps the KB privately. AI agent has read-access via a
                  separate mechanism, but other family members don't see files.
    - 'none'    — No KB connected. User only has bot-logged data.
    """
    body = await request.json()
    kb = body.get("kb_status")
    if kb not in ("shared", "private", "none", None):
        raise HTTPException(400, "Invalid kb_status")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(telegram_id=tg_id).first()
        if not u:
            raise HTTPException(404, "User not found")
        # Use raw SQL since kb_status not yet in ORM model (migration via ALTER)
        db.execute(
            text("UPDATE users SET kb_status = :v WHERE telegram_id = :t"),
            {"v": kb if kb != "none" else "none", "t": tg_id},
        )
        db.commit()
        logger.info(f"[admin] User {tg_id} kb_status → {kb}")
        return JSONResponse({"ok": True, "kb_status": kb})
    finally:
        db.close()


# ─── API: Server ───────────────────────────────────────────────────────────


def _human(b: int) -> str:
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    n = float(b)
    for u in units:
        if n < 1024 or u == units[-1]:
            return f"{n:.1f} {u}" if u != "Б" else f"{int(n)} {u}"
        n /= 1024
    return f"{b}"


def _du(path: str) -> str:
    """Human-readable disk usage of a path."""
    try:
        if not Path(path).exists():
            return "не смонтирован"
        out = subprocess.run(
            ["du", "-sh", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            return "—"
        return out.stdout.split()[0]
    except Exception as e:
        logger.warning(f"du failed for {path}: {e}")
        return "—"


@router.get("/api/llm_usage")
async def api_llm_usage(days: int = 7, _: str = Depends(admin_auth)) -> JSONResponse:
    """Aggregated LLM usage stats for admin panel.

    Three slices: by_purpose, by_day, by_user — plus overall totals.
    """
    from sqlalchemy import text as _text

    days = max(1, min(days, 365))
    db = SessionLocal()
    try:
        # Totals
        totals_row = db.execute(
            _text(
                """
                SELECT COUNT(*)                              AS calls,
                       COALESCE(SUM(input_tokens), 0)        AS input_tokens,
                       COALESCE(SUM(output_tokens), 0)       AS output_tokens,
                       COALESCE(SUM(cache_read_tokens), 0)   AS cache_read,
                       COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation,
                       COALESCE(SUM(cost_usd), 0)            AS cost_usd
                FROM llm_usage_log
                WHERE created_at >= NOW() - (:days || ' days')::interval
                """
            ),
            {"days": days},
        ).fetchone()

        # By purpose
        by_purpose = db.execute(
            _text(
                """
                SELECT purpose,
                       COUNT(*)                              AS calls,
                       COALESCE(SUM(input_tokens), 0)        AS input_tokens,
                       COALESCE(SUM(output_tokens), 0)       AS output_tokens,
                       COALESCE(SUM(cache_read_tokens), 0)   AS cache_read_tokens,
                       COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                       COALESCE(SUM(cost_usd), 0)            AS cost_usd
                FROM llm_usage_log
                WHERE created_at >= NOW() - (:days || ' days')::interval
                GROUP BY purpose
                ORDER BY cost_usd DESC
                """
            ),
            {"days": days},
        ).fetchall()

        # By day (pivoted on key purpose buckets)
        by_day = db.execute(
            _text(
                """
                SELECT DATE(created_at AT TIME ZONE 'Europe/Moscow') AS day,
                       COALESCE(SUM(cost_usd) FILTER (WHERE purpose='food_text'),  0) AS food_text_usd,
                       COALESCE(SUM(cost_usd) FILTER (WHERE purpose='food_photo'), 0) AS food_photo_usd,
                       COALESCE(SUM(cost_usd) FILTER (WHERE purpose IN ('agent_chat','agent_chat_tool')), 0) AS agent_chat_usd,
                       COALESCE(SUM(cost_usd), 0)            AS total_usd
                FROM llm_usage_log
                WHERE created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY 1 DESC
                """
            ),
            {"days": days},
        ).fetchall()

        # By user (top 20)
        by_user = db.execute(
            _text(
                """
                SELECT l.user_id,
                       u.first_name,
                       COUNT(*)                   AS calls,
                       COALESCE(SUM(l.cost_usd), 0) AS cost_usd
                FROM llm_usage_log l
                LEFT JOIN users u ON u.telegram_id = l.user_id
                WHERE l.created_at >= NOW() - (:days || ' days')::interval
                GROUP BY l.user_id, u.first_name
                ORDER BY cost_usd DESC
                LIMIT 20
                """
            ),
            {"days": days},
        ).fetchall()

        return JSONResponse(
            {
                "period_days": days,
                "totals": {
                    "calls": totals_row.calls,
                    "input_tokens": int(totals_row.input_tokens),
                    "output_tokens": int(totals_row.output_tokens),
                    "cache_read_tokens": int(totals_row.cache_read),
                    "cache_creation_tokens": int(totals_row.cache_creation),
                    "cost_usd": float(totals_row.cost_usd),
                },
                "by_purpose": [
                    {
                        "purpose": r.purpose,
                        "calls": r.calls,
                        "input_tokens": int(r.input_tokens),
                        "output_tokens": int(r.output_tokens),
                        "cache_read_tokens": int(r.cache_read_tokens),
                        "cache_creation_tokens": int(r.cache_creation_tokens),
                        "cost_usd": float(r.cost_usd),
                    }
                    for r in by_purpose
                ],
                "by_day": [
                    {
                        "day": r.day.isoformat(),
                        "food_text_usd": float(r.food_text_usd),
                        "food_photo_usd": float(r.food_photo_usd),
                        "agent_chat_usd": float(r.agent_chat_usd),
                        "total_usd": float(r.total_usd),
                    }
                    for r in by_day
                ],
                "by_user": [
                    {
                        "user_id": r.user_id,
                        "first_name": r.first_name,
                        "calls": r.calls,
                        "cost_usd": float(r.cost_usd),
                    }
                    for r in by_user
                ],
            }
        )
    finally:
        db.close()


@router.get("/api/server")
async def api_server(_: str = Depends(admin_auth)) -> JSONResponse:
    db = SessionLocal()
    try:
        # Database size and top tables
        size_row = db.execute(
            text(
                "SELECT pg_database_size(current_database()) AS s, pg_size_pretty(pg_database_size(current_database())) AS p"
            )
        ).first()
        top_tables = db.execute(
            text("""
            SELECT
              schemaname || '.' || tablename AS name,
              pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS size_pretty,
              pg_total_relation_size(schemaname || '.' || tablename) AS size_bytes,
              (SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = tablename LIMIT 1) AS rows
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
            LIMIT 10
        """)
        ).fetchall()

        # Disk usage of root partition (visible to bot container as / via shutil.disk_usage)
        usage = shutil.disk_usage("/")
        percent = round(usage.used / usage.total * 100, 1)

        return JSONResponse(
            {
                "db": {
                    "total_size": size_row.p,
                    "total_bytes": size_row.s,
                    "top_tables": [
                        {"name": r.name, "size_pretty": r.size_pretty, "size_bytes": r.size_bytes, "rows": r.rows or 0}
                        for r in top_tables
                    ],
                },
                "disk": {
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "total_pretty": _human(usage.total),
                    "used_pretty": _human(usage.used),
                    "free_pretty": _human(usage.free),
                    "percent": percent,
                },
                "paths": {
                    "healthvault": _du("/app"),
                    "backups": _du(str(BACKUPS_DIR)),
                    "data": _du("/app/data"),
                },
            }
        )
    finally:
        db.close()


# ─── API: Backups ──────────────────────────────────────────────────────────


@router.get("/api/backups")
async def api_backups_list(_: str = Depends(admin_auth)) -> JSONResponse:
    if not BACKUPS_DIR.exists():
        return JSONResponse({"count": 0, "backups": [], "warning": f"{BACKUPS_DIR} не примонтирован"})
    files = sorted(BACKUPS_DIR.glob("*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    backups = []
    for f in files[:30]:
        st = f.stat()
        backups.append(
            {
                "name": f.name,
                "size_bytes": st.st_size,
                "size_pretty": _human(st.st_size),
                "created": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return JSONResponse({"count": len(backups), "backups": backups})


@router.post("/api/backups")
async def api_backups_create(_: str = Depends(admin_auth)) -> JSONResponse:
    """Run pg_dump → gzip → /opt/backups/healthvault_YYYYMMDD_HHMMSS.sql.gz"""
    if not BACKUPS_DIR.exists():
        try:
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(500, f"Cannot create {BACKUPS_DIR}: {e}")

    db_url = os.getenv("DATABASE_URL", "")
    # Parse DSN
    pg_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or ""
    if not pg_password:
        # Try to extract from DATABASE_URL
        import re

        m = re.search(r"://[^:]+:([^@]+)@", db_url)
        if m:
            pg_password = m.group(1)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"healthvault_{ts}.sql.gz"
    fpath = BACKUPS_DIR / fname

    cmd = [
        "/bin/sh",
        "-c",
        f"PGPASSWORD='{pg_password}' pg_dump -h postgres -U healthvault -d healthvault --no-owner --no-acl | gzip -9 > '{fpath}'",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Backup timed out (>10 min)")
    if result.returncode != 0:
        # Cleanup partial file
        try:
            fpath.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(500, f"pg_dump failed: {result.stderr[:300]}")

    st = fpath.stat()
    logger.info(f"[admin] Backup created: {fname} ({_human(st.st_size)})")
    return JSONResponse(
        {
            "ok": True,
            "name": fname,
            "size_bytes": st.st_size,
            "size_pretty": _human(st.st_size),
        }
    )
