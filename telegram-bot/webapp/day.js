(function () {
  const tg = window.Telegram?.WebApp;
  tg?.expand();
  tg?.ready();

  const state = {
    date: new Date(),  // local date
    data: null,        // last /api/day response
    lastDeleted: null, // for undo
  };

  const FMT = new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' });
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
  document.querySelector('.day-label-wrap').addEventListener('click', (e) => {
    e.preventDefault();
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
    renderBudgetBanner();
    renderSlots();
    renderFooter();
  }

  function renderBudgetBanner() {
    const { totals_day: t, goals: g } = state.data;
    const banner = document.getElementById('budget-banner');
    if (!g || g.kcal == null) { banner.innerHTML = ''; return; }
    const remaining = Math.round(g.kcal - t.kcal);
    const pct = t.kcal / g.kcal;
    const cls = pct >= 1 ? 'over' : pct >= 0.85 ? 'warn' : 'ok';
    const label = remaining >= 0 ? `осталось ${remaining} ккал` : `перебор ${-remaining} ккал`;
    banner.innerHTML = `
      <span class="budget-remaining ${cls}">${label}</span>
      <span class="budget-macros">
        <span>Б ${Math.round(t.p)}г</span>
        <span>Ж ${Math.round(t.f)}г</span>
        <span>У ${Math.round(t.c)}г</span>
      </span>`;
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
      // Merge all meals in this slot into one card (items from each preserve their meal_id).
      const expandedKey = `exp:slot:${slot}`;
      const isExpanded = sessionStorage.getItem(expandedKey) !== '0';
      const hdrExtra = isExpanded ? '⌄' : '›';
      const totalKcal = meals.reduce((s, m) => s + (m.totals.kcal || 0), 0);
      const allItems = meals.flatMap(m => m.items);
      const previewText = allItems.map(it => it.name).join(' · ');
      const itemsHtml = isExpanded ? renderMergedItems(slot, meals) : '';
      return `
        <div class="slot" data-slot="${slot}">
          <div class="slot-header" data-toggle="slot:${slot}">
            <div class="slot-title">${SLOT_LABEL[slot]}</div>
            <div class="slot-meta">${Math.round(totalKcal)} ккал ${hdrExtra}</div>
          </div>
          ${!isExpanded ? `<div class="slot-preview">${escapeHtml(previewText)}</div>` : itemsHtml}
        </div>`;
    }).join('');

    container.querySelectorAll('.slot-header[data-toggle]').forEach(el => {
      el.addEventListener('click', () => {
        const key = `exp:${el.dataset.toggle}`;
        sessionStorage.setItem(key, sessionStorage.getItem(key) === '0' ? '1' : '0');
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

  function renderMergedItems(slot, meals) {
    const rows = [];
    for (const meal of meals) {
      for (const it of meal.items) rows.push({ meal, it });
    }
    const itemsHtml = rows.map(({ meal, it }) => {
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
    return `
    <div class="items">
      ${itemsHtml}
      <div class="add-in-slot" data-slot="${slot}">+ добавить в ${SLOT_LABEL[slot].replace(/^\S+\s/, '').toLowerCase()}</div>
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

  let activeSlot = null;

  async function openAddSheet(slot) {
    activeSlot = slot;
    document.getElementById('add-sheet-title').textContent =
      `Добавить в ${SLOT_LABEL[slot].replace(/^\S+\s/, '')}`;
    document.getElementById('add-sheet').classList.add('open');
    document.getElementById('add-name').value = '';
    document.getElementById('add-weight').value = '';
    document.getElementById('fav-list').innerHTML = '<div style="color:#999;font-size:12px">Загружаем…</div>';
    try {
      const favs = await api('/api/favorites?limit=15');
      document.getElementById('fav-list').innerHTML = favs.length
        ? favs.map(f => `
            <button class="fav-chip" data-name="${escapeHtml(f.name)}" data-weight="${f.default_weight}">
              ${escapeHtml(f.name)}
              <span class="w">${Math.round(f.default_weight)} г</span>
            </button>`).join('')
        : '<div style="color:#999;font-size:12px">Пока пусто</div>';
      document.querySelectorAll('.fav-chip').forEach(c => {
        c.addEventListener('click', () => {
          document.getElementById('add-name').value = c.dataset.name;
          document.getElementById('add-weight').value = c.dataset.weight;
        });
      });
    } catch (e) { console.error(e); }
  }

  function closeAddSheet() {
    document.getElementById('add-sheet').classList.remove('open');
    activeSlot = null;
  }

  document.getElementById('add-sheet-close').addEventListener('click', closeAddSheet);
  document.getElementById('add-sheet').addEventListener('click', (e) => {
    if (e.target.id === 'add-sheet') closeAddSheet();
  });

  document.getElementById('add-submit').addEventListener('click', async () => {
    const name = document.getElementById('add-name').value.trim();
    const weight = parseFloat(document.getElementById('add-weight').value);
    if (!name || !weight || weight <= 0) {
      tg?.showAlert?.('Заполни название и вес') ?? alert('Заполни название и вес');
      return;
    }
    const btn = document.getElementById('add-submit');
    btn.disabled = true; btn.textContent = 'Добавляем…';
    try {
      await api('/api/meal/item', {
        method: 'POST',
        body: JSON.stringify({
          date: toISO(state.date), slot: activeSlot,
          name, weight, source: 'manual',
        }),
      });
      closeAddSheet();
      await loadDay();
      tg?.HapticFeedback?.notificationOccurred?.('success');
    } catch (e) {
      tg?.showAlert?.(`Ошибка: ${e.message}`) ?? alert(e.message);
    } finally {
      btn.disabled = false; btn.textContent = 'Добавить';
    }
  });

  window.__openAddSheet = openAddSheet;  // for Task 11 renderer

  // Init
  updateSwitcher();
  loadDay();

function showSnackbar(text, onUndo) {
  const bar = document.getElementById('snackbar');
  document.getElementById('snackbar-text').textContent = text;
  bar.classList.remove('hidden');
  const undoBtn = document.getElementById('snackbar-undo');
  const handler = async () => { undoBtn.removeEventListener('click', handler); bar.classList.add('hidden'); await onUndo(); };
  undoBtn.addEventListener('click', handler);
  setTimeout(() => { bar.classList.add('hidden'); undoBtn.removeEventListener('click', handler); }, 4000);
}

function wireItemGestures(root) {
  root.querySelectorAll('.item').forEach(el => {
    let startX = 0, currentX = 0, dragging = false;
    const row = el.querySelector('.item-row');
    el.addEventListener('touchstart', (e) => {
      startX = e.touches[0].clientX; dragging = true;
    }, { passive: true });
    el.addEventListener('touchmove', (e) => {
      if (!dragging) return;
      currentX = e.touches[0].clientX - startX;
      if (currentX < 0) row.style.transform = `translateX(${Math.max(currentX, -100)}px)`;
    }, { passive: true });
    el.addEventListener('touchend', async () => {
      dragging = false;
      if (currentX < -60) {
        await deleteItem(el);
      } else {
        row.style.transform = '';
      }
      currentX = 0;
    });
    // Tap to edit weight
    row.addEventListener('click', (e) => {
      if (Math.abs(currentX) > 5) return;  // ignore if this was a swipe
      openEditSheet(el);
    });
  });
}
window.__wireItemGestures = wireItemGestures;

async function deleteItem(el) {
  const mealId = Number(el.dataset.mealId);
  const idx = Number(el.dataset.idx);
  try {
    const res = await api(`/api/meal/item?meal_id=${mealId}&idx=${idx}`, { method: 'DELETE' });
    const removed = res.removed;
    tg?.HapticFeedback?.impactOccurred?.('medium');
    showSnackbar(`Удалено: ${removed.name}`, async () => {
      // Undo: POST same product back to same slot
      const slot = el.closest('.slot')?.dataset.slot;
      await api('/api/meal/item', {
        method: 'POST',
        body: JSON.stringify({
          date: toISO(state.date), slot, name: removed.name,
          weight: removed.weight, source: 'manual',
        }),
      });
      loadDay();
    });
    loadDay();
  } catch (e) {
    tg?.showAlert?.(`Ошибка: ${e.message}`);
  }
}

function openEditSheet(el) {
  const mealId = Number(el.dataset.mealId);
  const idx = Number(el.dataset.idx);
  const meal = state.data.meals.find(m => m.id === mealId);
  const item = meal?.items[idx];
  if (!item) return;
  document.getElementById('edit-sheet-title').textContent = `Изменить: ${item.name}`;
  document.getElementById('edit-weight').value = item.weight;
  document.getElementById('edit-sheet').classList.add('open');
  document.getElementById('edit-submit').onclick = async () => {
    const w = parseFloat(document.getElementById('edit-weight').value);
    if (!w || w <= 0) return;
    try {
      await api('/api/meal/item', {
        method: 'PATCH',
        body: JSON.stringify({ meal_id: mealId, idx, weight: w }),
      });
      document.getElementById('edit-sheet').classList.remove('open');
      tg?.HapticFeedback?.notificationOccurred?.('success');
      loadDay();
    } catch (e) {
      tg?.showAlert?.(`Ошибка: ${e.message}`);
    }
  };
}

document.getElementById('edit-sheet-close').addEventListener('click', () =>
  document.getElementById('edit-sheet').classList.remove('open')
);
document.getElementById('edit-sheet').addEventListener('click', (e) => {
  if (e.target.id === 'edit-sheet') e.target.classList.remove('open');
});
})();
