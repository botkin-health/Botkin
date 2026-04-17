(function () {
  const tg = window.Telegram?.WebApp;
  tg?.expand();
  tg?.ready();

  const state = {
    date: new Date(),  // local date
    data: null,        // last /api/day response
    lastDeleted: null, // for undo
  };

  const FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', weekday: 'short' });
  const SLOT_LABEL = { breakfast: '🌅 Завтрак', lunch: '☀️ Обед', snack: '🍎 Перекус', dinner: '🌙 Ужин' };

  function toISO(d) {
    const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'),
          dd = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${dd}`;
  }
  function sameDay(a, b) { return toISO(a) === toISO(b); }
  function daysDiff(a, b) {
    const ms = (new Date(toISO(b))) - (new Date(toISO(a)));
    return Math.round(ms / 86400000);
  }

  function dayLabelText(d) {
    const today = new Date();
    if (sameDay(d, today)) return 'Сегодня';
    const y = new Date(today); y.setDate(y.getDate() - 1);
    if (sameDay(d, y)) return 'Вчера';
    const t = new Date(today); t.setDate(t.getDate() + 1);
    if (sameDay(d, t)) return 'Завтра';
    return FMT.format(d);
  }

  async function api(path, options = {}) {
    const initData = tg?.initData || '';
    const headers = { 'Authorization': `tma ${initData}`, 'Content-Type': 'application/json', ...(options.headers || {}) };
    const r = await fetch(path, { ...options, headers });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.status === 204 ? null : r.json();
  }

  async function loadDay() {
    try {
      state.data = await api(`/api/day?date=${toISO(state.date)}`);
      render();
    } catch (e) {
      console.error(e);
      document.getElementById('slots-container').innerHTML =
        `<div style="padding:20px;text-align:center;color:#999">Нет связи: ${e.message}</div>`;
    }
  }

  function setDate(d) {
    state.date = d;
    updateSwitcher();
    loadDay();
  }

  function updateSwitcher() {
    const d = state.date, today = new Date();
    document.getElementById('day-label').textContent = dayLabelText(d);
    document.getElementById('day-sub').textContent = FMT.format(d);
    // Disable next-day if more than +7 days ahead
    document.getElementById('next-day').disabled = daysDiff(today, d) >= 7;
    document.getElementById('date-picker').value = toISO(d);
  }

  // Wire up controls
  document.getElementById('prev-day').addEventListener('click', () => {
    const d = new Date(state.date); d.setDate(d.getDate() - 1); setDate(d);
  });
  document.getElementById('next-day').addEventListener('click', () => {
    if (document.getElementById('next-day').disabled) return;
    const d = new Date(state.date); d.setDate(d.getDate() + 1); setDate(d);
  });
  document.querySelector('.calendar-btn').addEventListener('click', (e) => {
    // Opens native date picker when clicking the hidden input
    document.getElementById('date-picker').showPicker?.();
  });
  document.getElementById('date-picker').addEventListener('change', (e) => {
    if (e.target.value) setDate(new Date(e.target.value + 'T00:00:00'));
  });

  // Settings toggle
  document.getElementById('toggle-settings').addEventListener('click', () => {
    const day = document.getElementById('day-section');
    const set = document.getElementById('settings-section');
    const isOnDay = day.classList.contains('active');
    day.classList.toggle('active', !isOnDay);
    set.classList.toggle('active', isOnDay);
    document.getElementById('top-title').textContent = isOnDay ? '⚙️ Настройки' : '🍽 Дневник';
    document.getElementById('toggle-settings').textContent = isOnDay ? '✕' : '⚙️';
  });

  // Render functions defined in Task 11 / 12.
  function render() { /* filled in Task 11 */ window.__dayRender?.(state); }

  // Expose for later tasks
  window.__nutri = { state, api, loadDay, render, setDate };

  // Init
  updateSwitcher();
  loadDay();
})();
