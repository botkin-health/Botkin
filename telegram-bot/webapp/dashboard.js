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
    if (r.status === 404) {
      container.innerHTML = dashboardEmptyState(
        'Открой бота командой /start, потом вернись сюда — дашборд появится.'
      );
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { token } = await r.json();
    if (!token) throw new Error('empty token');

    const iframe = document.createElement('iframe');
    iframe.className = 'dashboard-frame';
    iframe.src = '/mc/' + encodeURIComponent(token);
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
