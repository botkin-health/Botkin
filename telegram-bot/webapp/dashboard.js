// ── Dashboard tab — embeds the personal dashboard (/mc/{token}) in an iframe ──
// Lazy: builds the iframe on first open, then reuses it (no reload on re-tap).
// loadDashboard() is global — switchTab() in settings.js calls it.

const tgDash = window.Telegram?.WebApp;
let _dashboardLoaded = false;

async function loadDashboard() {
  if (_dashboardLoaded) return; // iframe already built — keep it cached
  const container = document.getElementById('dashboard-container');
  if (!container) return;

  container.innerHTML = '<div class="dashboard-loading">Загружаем дашборд…</div>';

  try {
    const r = await fetch('/api/dashboard_url', {
      headers: { Authorization: 'tma ' + (tgDash?.initData || '') },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { token } = await r.json();
    if (!token) {
      // no-user (mini-app открыт до /start): эндпоинт отдаёт 200 {token:null}.
      // Подсказка без Retry — повтор всё равно вернёт null, пока юзер не нажал /start.
      container.innerHTML = dashboardEmptyState(
        'Открой бота командой /start, потом вернись сюда — дашборд появится.'
      );
      return;
    }

    const iframe = document.createElement('iframe');
    iframe.className = 'dashboard-frame';
    // ?embed=1 — scale-to-fit вариант дашборда под узкий экран мини-аппа.
    iframe.src = '/mc/' + encodeURIComponent(token) + '?embed=1';
    iframe.addEventListener('error', () => {
      _dashboardLoaded = false;
      container.innerHTML =
        dashboardEmptyState('Не удалось открыть дашборд.') + retryButton();
    });
    container.innerHTML = '';
    container.appendChild(iframe);
    _dashboardLoaded = true;
  } catch (e) {
    console.error('loadDashboard failed', e);
    container.innerHTML =
      dashboardEmptyState('Не удалось загрузить — попробуй ещё раз.') + retryButton();
  }
}

function retryDashboard() {
  _dashboardLoaded = false;
  loadDashboard();
}

function retryButton() {
  return '<button class="dashboard-retry" onclick="retryDashboard()">Повторить</button>';
}

function dashboardEmptyState(msg) {
  return `<div class="supp-empty-state">
    <div class="icon">📊</div>
    <div class="title">Дашборд недоступен</div>
    <div class="hint">${msg}</div>
  </div>`;
}

// ── «Экспорт для врача» — PDF-отчёт в чат (#290) ─────────────────────────────
// Основной путь доставки: кнопка на вкладке «Здоровье» → POST /api/doctor_report
// → бот присылает PDF Telegram-документом. Кнопка живёт в chrome мини-аппа
// (не внутри iframe /mc/), поэтому на дашборде, расшаренном врачу, её нет.
async function requestDoctorReport() {
  const btn = document.getElementById('doctor-export-btn');
  const statusEl = document.getElementById('doctor-export-status');
  const orig = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Готовим PDF…'; }
  if (statusEl) { statusEl.textContent = ''; statusEl.className = 'doctor-export-status'; }
  try {
    await window.API.requestDoctorReport();
    if (statusEl) { statusEl.textContent = '✓ PDF отправлен в чат'; statusEl.className = 'doctor-export-status ok'; }
  } catch (e) {
    console.error('requestDoctorReport failed', e);
    if (statusEl) { statusEl.textContent = '⚠ Не удалось сформировать. Попробуйте позже.'; statusEl.className = 'doctor-export-status error'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}
