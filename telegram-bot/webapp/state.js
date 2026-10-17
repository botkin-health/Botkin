// ── Вкладка «Состояние» — сводка по потокам здоровья ─────────────────────────
// Данные: GET /api/health/summary (контракт — docs/projects/2026-10_miniapp-health-tab/PROPOSAL.md, 4.1).
// Потоки без данных (not_connected / no_data / нет ключа) не рисуем вообще: у многих
// пользователей части данных нет. Графики — div-бары, без библиотек; null = пропуск.
// loadState() — глобальная, её зовёт switchTab() в settings.js.
// Проверка без бэкенда: открыть миниапп с ?mock=full | sparse | quiet | newbie
// (сценарии лежат в state.fixture.json, числа вымышленные).

const STATE_VISIBLE = ['ok', 'attention', 'stale', 'insufficient'];
const STATE_REFRESH_MS = 60 * 1000;
let _stateFetchedAt = 0;
let _stateLoading = false;

function stEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// 5,9 · 8 420 · 1,14 — запятая и тонкие пробелы как в остальном миниаппе.
function stNum(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('ru-RU', { maximumFractionDigits: digits });
}

function stDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[3]}.${m[2]}` : '';
}

function stDaysBetween(fromIso, toIso) {
  const a = Date.parse(fromIso), b = Date.parse(toIso);
  return Number.isNaN(a) || Number.isNaN(b) ? null : Math.round((b - a) / 86400000);
}

// «сегодня» / «вчера» / «09.10»
function stWhen(iso, asOf) {
  const d = stDaysBetween(iso, asOf);
  if (d === 0) return 'сегодня';
  if (d === 1) return 'вчера';
  return stDate(iso);
}

function stHeaderDate(asOf) {
  const months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(asOf || '');
  return m ? `сегодня, ${Number(m[3])} ${months[Number(m[2]) - 1]}` : '';
}

function stIsShown(s) {
  return !!s && STATE_VISIBLE.includes(s.status) && s.connected !== false;
}

// ── Мини-график на 7 дней ────────────────────────────────────────────────────
function stSpark(series, unit) {
  const pts = Array.isArray(series) ? series : [];
  const vals = pts.map(p => p.value).filter(v => v !== null && v !== undefined);
  if (vals.length < 2) return '';
  const min = Math.min(...vals), max = Math.max(...vals);
  const bars = pts.map((p, i) => {
    const last = i === pts.length - 1 ? ' last' : '';
    if (p.value === null || p.value === undefined) {
      return `<i class="gap" title="${stEsc(stDate(p.date))}: нет данных"></i>`;
    }
    const h = max === min ? 60 : 22 + 78 * (p.value - min) / (max - min);
    const tip = `${stDate(p.date)}: ${stNum(p.value)}${unit ? ' ' + unit : ''}`;
    return `<i class="${last.trim()}" style="height:${h.toFixed(0)}%" title="${stEsc(tip)}"></i>`;
  }).join('');
  return `<div class="st-spark" aria-hidden="true">${bars}</div>`;
}

// ── Карточка потока ──────────────────────────────────────────────────────────
function stCard(title, main, lines, spark, extraCls = '') {
  const sub = lines.filter(Boolean).map(l => `<div class="st-sub">${l}</div>`).join('');
  return `<div class="st-card ${extraCls}">
    <div class="st-card-body">
      <div class="st-card-title">${stEsc(title)}</div>
      <div class="st-main">${main}</div>
      ${sub}
    </div>
    ${spark}
  </div>`;
}

function stLatestValue(s) {
  const l = s.latest || {};
  if (l.value2 != null) return `${stNum(l.value, 0)}/${stNum(l.value2, 0)}`; // давление: value/value2
  return stNum(l.value);
}

function stStale(s, asOf) {
  const days = s.stale_days ?? stDaysBetween(s.last_date || s.latest?.date, asOf);
  return days != null ? `замер ${stNum(days, 0)} дн. назад` : 'давно не обновлялось';
}

function stAvgLine(s) {
  if (!s.avg || s.avg.value == null) return '';
  const unit = s.avg.unit ? ' ' + s.avg.unit : '';
  const n = s.avg.n != null ? `, N=${s.avg.n}` : '';
  return `${stEsc(s.avg.label || 'среднее')} ${stNum(s.avg.value)}${stEsc(unit)}${n}`;
}

// Строки под значением: свежий факт с датой, среднее с N, специфика потока.
// stale — последнее значение серым с подписью «замер N дн. назад», без графика.
function stCardFor(title, s, asOf, extraLines) {
  const unit = s.latest?.unit ? `<span class="st-unit"> ${stEsc(s.latest.unit)}</span>` : '';
  const main = `${stEsc(stLatestValue(s))}${unit}`;
  if (s.status === 'stale') return stCard(title, main, [stEsc(stStale(s, asOf))], '', 'stale');
  const when = s.latest?.date ? stEsc(stWhen(s.latest.date, asOf)) : '';
  const few = s.status === 'insufficient' ? 'мало данных для сравнения' : '';
  return stCard(title, main, [when, few, stAvgLine(s), ...extraLines], stSpark(s.series, s.latest?.unit));
}

function stRenderSleep(s, asOf) { return stCardFor('Сон', s, asOf, []); }

function stRenderActivity(s, asOf) {
  const w = s.workouts || s.extra?.workouts;
  const wl = w && w.count != null
    ? `тренировок за ${s.window_days || 7} дн.: ${stNum(w.count, 0)}${w.minutes != null ? ` · ${stNum(w.minutes, 0)} мин` : ''}`
    : '';
  return stCardFor('Активность', s, asOf, [stEsc(wl)]);
}

function stRenderHrv(s, asOf) {
  const h = s.extra?.pulse; // карточка пульса: {latest, avg, kind: resting|mixed}
  const hv = h?.latest?.value;
  const hl = hv != null ? `${h.kind === 'resting' ? 'пульс покоя' : 'пульс'} ${stNum(hv, 0)} ${stEsc(h.latest.unit || 'уд/мин')}` : '';
  const src = s.extra?.source ? `источник: ${stEsc(s.extra.source)}` : '';
  return stCardFor('HRV и пульс', s, asOf, [hl, src]);
}

function stRenderWeight(s, asOf) {
  const fat = s.extra?.body_fat;
  const fl = fat && (fat.value ?? fat) != null ? `жир ${stNum(fat.value ?? fat)}${fat.unit ? ' ' + stEsc(fat.unit) : ' %'}` : '';
  return stCardFor('Вес', s, asOf, [fl]);
}

function stRenderBp(s, asOf) { return stCardFor('Давление', s, asOf, []); }

function stRenderGlucose(s, asOf) {
  const tir = s.extra?.tir_pct;
  const tl = tir != null ? `в целевом диапазоне за ${s.window_days || 7} дн.: ${stNum(tir, 0)} %` : '';
  return stCardFor('Глюкоза', s, asOf, [stEsc(tl)]);
}

// ── Анализы ──────────────────────────────────────────────────────────────────
function stLabsHasContent(l) {
  return !!l && STATE_VISIBLE.includes(l.status) &&
    !!(l.last_test_date || (l.out_of_range || []).length || (l.stale || []).length);
}

function stRenderLabItem(m) {
  const ref = m.ref_low != null || m.ref_high != null
    ? `норма ${m.ref_low != null && m.ref_low > 0 ? stNum(m.ref_low, 2) : ''}${m.ref_low > 0 && m.ref_high != null ? '–' : (m.ref_high != null ? 'до ' : '')}${m.ref_high != null ? stNum(m.ref_high, 2) : ''}`
    : '';
  const dir = m.direction === 'high' ? 'выше нормы' : (m.direction === 'low' ? 'ниже нормы' : '');
  const hist = (m.history || []).filter(h => h.value != null);
  const histLine = hist.length >= 2
    ? `<div class="st-sub">${hist.map(h => stNum(h.value, 2)).join(' → ')} <span class="st-faint">(с ${stEsc(stDate(hist[0].date))})</span></div>`
    : '';
  return `<div class="st-lab">
    <div class="st-lab-row"><b>${stEsc(m.label || m.key)}</b><span>${stNum(m.value, 2)} ${stEsc(m.unit || '')}</span></div>
    <div class="st-sub">${[dir, ref, m.date ? 'анализ от ' + stDate(m.date) : ''].filter(Boolean).map(stEsc).join(' · ')}</div>
    ${histLine}
  </div>`;
}

function stRenderLabs(l) {
  const out = l.out_of_range || [];
  const stale = l.stale || [];
  const head = l.last_test_date ? `Анализы · последние ${stDate(l.last_test_date)}` : 'Анализы';
  const parts = [];
  if (out.length) parts.push(`${out.length} вне нормы`);
  if (stale.length) parts.push(`${stale.length} просрочено`);
  const summary = parts.length ? parts.join(' · ') : (l.n_markers ? `маркеров в базе: ${l.n_markers}` : '');
  const note = l.ref_note ? `<div class="st-sub st-note">${stEsc(l.ref_note)}</div>` : '';
  const expandable = out.length || stale.length || l.ref_note;
  const body = `${out.map(stRenderLabItem).join('')}
    ${stale.length ? `<div class="st-lab"><div class="st-lab-row"><b>Давно не сдавали</b></div>${
      stale.map(s => `<div class="st-sub">${stEsc(s.label || s.key)} — ${stNum(s.days_ago, 0)} дн. назад</div>`).join('')}</div>` : ''}
    ${note}`;
  return `<div class="st-card st-labs${out.length ? ' attention' : ''}">
    <button type="button" class="st-labs-head" ${expandable ? 'aria-expanded="false"' : 'disabled'}
      onclick="toggleStateLabs(this)">
      <div class="st-card-body">
        <div class="st-card-title">${stEsc(head)}</div>
        <div class="st-main st-main-sm">${stEsc(summary || 'нет флагов')}</div>
      </div>
      ${expandable ? '<svg class="ic st-chev"><use href="#i-chev-d"/></svg>' : ''}
    </button>
    <div class="st-labs-body" hidden>${body}</div>
  </div>`;
}

function toggleStateLabs(btn) {
  const body = btn.parentElement.querySelector('.st-labs-body');
  const open = body.hidden;
  body.hidden = !open;
  btn.setAttribute('aria-expanded', String(open));
  btn.classList.toggle('open', open);
}

// ── «На что обратить внимание» ───────────────────────────────────────────────
// Пустой attention ≠ «всё хорошо»: нейтральная фраза — только когда есть из чего
// сравнивать (у потока есть baseline); иначе честно «недостаточно данных».
function stHasComparison(streams) {
  return Object.values(streams).some(s => stIsShown(s) && s.status !== 'stale' && s.baseline && s.baseline.n >= 7);
}

function stRenderAttention(d) {
  const items = (d.attention || []).slice(0, 4);
  let body;
  if (items.length) {
    body = items.map(a => `<div class="st-att ${stEsc(a.severity || 'info')}">
      <div class="st-att-title">${stEsc(a.title)}</div>
      ${a.detail ? `<div class="st-sub">${stEsc(a.detail)}</div>` : ''}
      ${a.action ? `<div class="st-action">${stEsc(a.action)}</div>` : ''}
    </div>`).join('');
  } else if (stHasComparison(d.streams || {})) {
    body = `<div class="st-empty">В рамках своей нормы за ${stNum(d.window_days || 7, 0)} дн.</div>`;
  } else {
    body = '<div class="st-empty">Недостаточно данных для сравнения</div>';
  }
  return `<div class="st-title">На что обратить внимание</div>${body}`;
}

// ── Нижние кнопки: дашборд, ссылка на него и PDF ─────────────────────────────────────────────
function stRenderActions() {
  return `<div class="st-actions">
    <button type="button" class="st-btn" onclick="switchTab('dashboard')">
      <svg class="ic"><use href="#i-chart"/></svg>Открыть дашборд
    </button>
    <button type="button" class="st-btn" onclick="copyDashboard()">
      <svg class="ic"><use href="#i-copy"/></svg>Скопировать ссылку на дашборд
    </button>
    <button type="button" class="st-btn" onclick="toggleDoctorLang('state')">
      <svg class="ic"><use href="#i-file"/></svg>Отчёт для врача (PDF)
    </button>
    <div id="state-doctor-lang-choice" class="doctor-lang-choice" hidden>
      <span class="doctor-lang-prompt">Язык:</span>
      <button type="button" class="lang-choice-btn" onclick="requestDoctorReport('ru', 'state')">Русский</button>
      <button type="button" class="lang-choice-btn" onclick="requestDoctorReport('en', 'state')">English</button>
      <button type="button" class="lang-choice-cancel" onclick="toggleDoctorLang('state')" aria-label="Отмена"><svg class="ic"><use href="#i-x"/></svg></button>
    </div>
    <div id="state-doctor-export-status" class="doctor-export-status"></div>
  </div>`;
}

function stRenderEmptyNewbie() {
  return `<div class="st-card st-newbie">
    <div class="st-card-title">Пока нет данных</div>
    <div class="st-sub">Подключи часы или Apple Health, чтобы здесь появилась картина: сон, шаги, пульс и вес.
    Источники — в Настройках.</div>
  </div>`;
}

// ── Экран целиком ────────────────────────────────────────────────────────────
function renderState(d) {
  const root = document.getElementById('state-container');
  if (!root) return;
  const streams = d.streams || {};
  const asOf = d.as_of;
  const win = d.window_days || 7;
  const renderers = [
    ['sleep', stRenderSleep], ['activity', stRenderActivity], ['hrv', stRenderHrv],
    ['weight', stRenderWeight], ['bp', stRenderBp], ['glucose', stRenderGlucose],
  ];
  const cards = renderers
    .filter(([k]) => stIsShown(streams[k]))
    .map(([k, fn]) => fn({ window_days: win, ...streams[k] }, asOf));
  const labs = stLabsHasContent(streams.labs) ? stRenderLabs(streams.labs) : '';
  const nothing = !cards.length && !labs;

  root.innerHTML = `
    <div class="st-header"><b>Состояние</b><span>${stEsc(stHeaderDate(asOf))}</span></div>
    ${nothing ? '' : stRenderAttention({ ...d, streams })}
    ${nothing ? stRenderEmptyNewbie() : `
      ${cards.length ? `<div class="st-title">Потоки за ${stNum(win, 0)} дн.</div>${cards.join('')}` : ''}
      ${labs}`}
    ${stRenderActions()}`;
}

function renderStateMessage(html) {
  const root = document.getElementById('state-container');
  if (root) root.innerHTML = `<div class="st-header"><b>Состояние</b></div>${html}`;
}

async function loadState(force = false) {
  const root = document.getElementById('state-container');
  if (!root || _stateLoading) return;
  if (!force && Date.now() - _stateFetchedAt < STATE_REFRESH_MS && root.children.length) return;
  _stateLoading = true;
  if (!root.children.length) renderStateMessage('<div class="st-empty">Загружаем…</div>');
  try {
    const mock = new URLSearchParams(location.search).get('mock');
    let data;
    if (mock) {
      const all = await (await fetch('state.fixture.json')).json();
      data = all[mock === '1' ? 'full' : mock];
      if (!data) throw new Error('unknown mock scenario: ' + mock);
    } else {
      data = await window.API.getHealthSummary(7);
    }
    renderState(data);
    _stateFetchedAt = Date.now();
  } catch (e) {
    // 404 — бэкенд сводки ещё не выкачен (фронт вкладки уехал раньше API): не пугаем
    // ошибкой, а честно говорим «скоро» и оставляем рабочие кнопки ниже.
    if (String(e && e.message).startsWith('404')) {
      renderStateMessage(`<div class="st-empty st-soon">
          <div class="st-soon-title">Скоро здесь будет сводка</div>
          Сон, активность, пульс, вес и анализы — и на что обратить внимание.
          Пока всё это есть на дашборде.
        </div>
        ${stRenderActions()}`);
      return;
    }
    console.error('loadState failed', e);
    renderStateMessage(`<div class="st-empty">Не удалось загрузить данные.</div>
      <button type="button" class="st-btn" onclick="loadState(true)">Повторить</button>
      ${stRenderActions()}`);
  } finally {
    _stateLoading = false;
  }
}
