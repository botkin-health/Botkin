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
  function render() {
    if (!state.data) return;
    renderSlots();
    renderFooter();
  }

  function renderSlots() {
    const container = document.getElementById('slots-container');
    const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner'];
    // Group meals by slot
    const bySlot = { breakfast: [], lunch: [], snack: [], dinner: [] };
    for (const m of state.data.meals) bySlot[m.slot]?.push(m);

    container.innerHTML = SLOTS.map(slot => {
      const meals = bySlot[slot];
      if (meals.length === 0) {
        return `
        <div class="slot dim" data-slot="${slot}">
          <div class="slot-header">
            <div class="slot-title">${SLOT_LABEL[slot]}</div>
            <button class="header-btn add-in-slot-btn" data-slot="${slot}">+</button>
          </div>
          <div class="slot-empty">Пока ничего</div>
        </div>`;
      }
      // If 2+ meals fall into the same slot, render each as its own card inside the slot.
      return meals.map((m, mi) => {
        const expandedKey = `exp:${m.id}`;
        const isExpanded = sessionStorage.getItem(expandedKey) === '1' || (meals.length === 1);
        const hdrExtra = isExpanded ? '⌄' : '›';
        const itemsHtml = isExpanded ? renderItems(m) : '';
        return `
        <div class="slot" data-slot="${slot}" data-meal-id="${m.id}">
          <div class="slot-header" data-toggle="${m.id}">
            <div class="slot-title">${SLOT_LABEL[slot]}
              <span class="slot-meta">· ${m.meal_time || ''}</span>
            </div>
            <div class="slot-meta">${Math.round(m.totals.kcal)} ккал ${hdrExtra}</div>
          </div>
          ${itemsHtml}
        </div>`;
      }).join('');
    }).join('');

    container.querySelectorAll('.slot-header[data-toggle]').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.toggle;
        const key = `exp:${id}`;
        sessionStorage.setItem(key, sessionStorage.getItem(key) === '1' ? '0' : '1');
        renderSlots();
      });
    });
    container.querySelectorAll('.add-in-slot-btn, .add-in-slot').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        openAddSheet(el.dataset.slot);
      });
    });
    // Swipe + tap: wired in Task 13.
    window.__wireItemGestures?.(container);
  }

  function renderItems(meal) {
    const hintShown = localStorage.getItem('swipeHintShown') === '1';
    const itemsHtml = meal.items.map(it => {
      const noMacros = it.kcal === 0 && it.p === 0 && it.f === 0 && it.c === 0;
      const warn = noMacros ? '<span class="item-warn">❗</span> ' : '';
      return `
      <div class="item" data-meal-id="${meal.id}" data-idx="${it.idx}">
        <div class="delete-bg">Удалить</div>
        <div class="item-row">
          <div class="item-name">${warn}${escapeHtml(it.name)}</div>
          <div class="item-weight">${Math.round(it.weight)} г</div>
          <div class="item-macros">
            <span>Б <b>${it.p}</b></span>
            <span>Ж <b>${it.f}</b></span>
            <span>У <b>${it.c}</b></span>
            <span>Кл <b>${it.fib}</b></span>
            <span>${Math.round(it.kcal)} ккал</span>
          </div>
        </div>
      </div>`;
    }).join('');
    const hint = hintShown ? '' : '<div class="swipe-hint">← свайп для удаления · тап для редактирования веса</div>';
    return `
    <div class="items">
      ${itemsHtml}
      ${hint}
      <div class="add-in-slot" data-slot="${meal.slot}">+ добавить в ${SLOT_LABEL[meal.slot].replace(/^\S+\s/, '').toLowerCase()}</div>
    </div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function renderFooter() {
    const { totals_day: t, goals: g } = state.data;
    const bars = [
      { key: 'kcal',   label: 'Ккал',      cls: 'kcal', val: t.kcal,  goal: g.kcal,    unit: '' },
      { key: 'p',      label: 'Белки',     cls: 'p',    val: t.p,     goal: g.protein, unit: 'г' },
      { key: 'f',      label: 'Жиры',      cls: 'f',    val: t.f,     goal: g.fats,    unit: 'г' },
      { key: 'c',      label: 'Углеводы',  cls: 'c',    val: t.c,     goal: g.carbs,   unit: 'г' },
      { key: 'fib',    label: 'Клетчатка', cls: 'fib',  val: t.fib,   goal: g.fiber,   unit: 'г' },
    ];
    document.getElementById('bars').innerHTML = bars.map(b => {
      if (b.goal == null) {
        return `<div class="bar-row">
                <span>${b.label}</span>
                <div></div>
                <span class="bar-value">${Math.round(b.val)}${b.unit ? ' ' + b.unit : ''}</span>
              </div>`;
      }
      const pct = Math.min(100, Math.round((b.val / b.goal) * 100));
      return `<div class="bar-row">
              <span>${b.label}</span>
              <div class="bar-track"><div class="bar-fill ${b.cls}" style="width:${pct}%"></div></div>
              <span class="bar-value">${Math.round(b.val)} <span>/ ${b.goal}${b.unit ? ' ' + b.unit : ''}</span></span>
            </div>`;
    }).join('');
  }

  // Expose for later tasks
  window.__nutri = { state, api, loadDay, render, setDate };

  // Init
  updateSwitcher();
  loadDay();
})();
