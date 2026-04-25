(function () {
  const tg = window.Telegram?.WebApp;
  tg?.expand();
  tg?.ready();

  const state = {
    date: new Date(),  // local date
    data: null,        // last /api/day response
    lastDeleted: null, // for undo
  };

  const FMT = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
  const SLOT_LABEL = { breakfast: '🌅 Завтрак', lunch: '☀️ Обед', snack: '🍎 Перекусы', dinner: '🌙 Ужин' };

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
    const s = FMT.format(d);
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // API client lives in api.js → window.API
  const API = window.API;

  async function loadDay() {
    try {
      state.data = await API.getDay(toISO(state.date));
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
    const lbl = document.getElementById('day-label');
    if (lbl) lbl.textContent = dayLabelText(d);
    const nextBtn = document.getElementById('next-day');
    if (nextBtn) nextBtn.disabled = daysDiff(today, d) >= 7;
    const picker = document.getElementById('date-picker');
    if (picker) picker.value = toISO(d);
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

    const consumed = Math.round(t.kcal || 0);
    const goal = Math.round(g.kcal);
    const diff = goal - consumed;
    const isOver = diff < 0;
    const cls = isOver ? 'over' : diff / goal < 0.15 ? 'warn' : 'ok';

    const heroText = isOver ? `−${Math.abs(diff)} ккал` : `+${diff} ккал`;
    const subText = isOver
      ? `перебор · съедено ${consumed} из ${goal}`
      : `осталось · съедено ${consumed} из ${goal}`;

    // Right column: BMR / activity / deficit (show only if data available)
    let infoCol = '';
    if (g.bmr || g.activity_today != null || g.activity_avg || g.deficit_pct) {
      const lines = [];
      if (g.bmr) lines.push(`💤 БМР ${g.bmr}`);
      if (g.activity_today != null) {
        const avgSuffix = g.activity_avg ? ` · ${g.activity_avg} ср.` : '';
        lines.push(`🏃 ${g.activity_today} сег.${avgSuffix}`);
      } else if (g.activity_avg) {
        lines.push(`🏃 ${g.activity_avg} ккал`);
      }
      if (g.deficit_pct) lines.push(`🎯 −${g.deficit_pct}% дефицит`);
      infoCol = `<div class="budget-info-col">${lines.join('<br>')}</div>`;
    }

    banner.innerHTML = `
    <div class="budget-banner-inner">
      <div>
        <span class="budget-remaining ${cls}">${heroText}</span>
        <span class="budget-sub">${subText}</span>
      </div>
      ${infoCol}
    </div>`;
  }

  function renderSlots() {
    const container = document.getElementById('slots-container');
    const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner'];
    // Group meals by slot
    const bySlot = { breakfast: [], lunch: [], snack: [], dinner: [] };
    for (const m of state.data.meals) bySlot[m.slot]?.push(m);

    container.innerHTML = `<div class="slots-section">${SLOTS.map(slot => {
      const meals = bySlot[slot];
      if (meals.length === 0) {
        return `
        <div class="slot dim" data-slot="${slot}">
          <div class="slot-left">
            <div class="slot-title">${SLOT_LABEL[slot]}</div>
            <div class="slot-empty">Пусто</div>
          </div>
          <div class="slot-right">
            <span class="slot-meta" style="color:#c7c7cc;">—</span>
          </div>
        </div>`;
      }
      // Merge all meals in this slot into one card (items from each preserve their meal_id).
      const expandedKey = `exp:slot:${slot}`;
      const isExpanded = sessionStorage.getItem(expandedKey) === '1';
      const hdrExtra = isExpanded ? '⌄' : '›';
      const totalKcal = meals.reduce((s, m) => s + (m.totals.kcal || 0), 0);
      const totalFib  = meals.reduce((s, m) => s + (m.totals.fib  || 0), 0);
      const allItems = meals.flatMap(m => m.items);
      const previewText = allItems.map(it => it.name).join(' · ');
      const itemsHtml = isExpanded ? renderMergedItems(slot, meals) : '';
      return `
        <div class="slot ${isExpanded ? 'expanded' : ''}" data-slot="${slot}">
          <div class="slot-header-row" data-toggle="slot:${slot}" style="display:flex;justify-content:space-between;align-items:flex-start;cursor:pointer;width:100%">
            <div class="slot-left" style="flex:1;min-width:0;">
              <div class="slot-title">${SLOT_LABEL[slot]}</div>
              ${!isExpanded ? `<div class="slot-preview">${escapeHtml(previewText)}</div>` : ''}
            </div>
            <div class="slot-right" style="flex-shrink:0;padding-left:8px;text-align:right;">
              <div class="slot-meta">${Math.round(totalKcal)}</div>
              ${totalFib > 0 ? `<div class="slot-fiber">Кл ${Math.round(totalFib)} г</div>` : ''}
            </div>
          </div>
          ${isExpanded ? itemsHtml : ''}
        </div>`;
    }).join('')}</div>`;

    container.querySelectorAll('[data-toggle]').forEach(el => {
      el.addEventListener('click', () => {
        const key = `exp:${el.dataset.toggle}`;
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
      { label: 'Ккал',      cls: 'kcal', val: t.kcal, goal: g?.kcal,    unit: '',  moreIsBetter: false },
      { label: 'Белки',     cls: 'p',    val: t.p,    goal: g?.protein, unit: 'г', moreIsBetter: true  },
      { label: 'Жиры',      cls: 'f',    val: t.f,    goal: g?.fats,    unit: 'г', moreIsBetter: false },
      { label: 'Углев.',    cls: 'c',    val: t.c,    goal: g?.carbs,   unit: 'г', moreIsBetter: false },
      { label: 'Клетчатка', cls: 'fib',  val: t.fib,  goal: g?.fiber,   unit: 'г', moreIsBetter: true  },
    ];
    document.getElementById('bars').innerHTML = bars.map(b => {
      if (b.goal == null) {
        return `<div class="bar-row">
              <span>${b.label}</span>
              <div></div>
              <span class="bar-value">${Math.round(b.val || 0)} ${b.unit}</span>
            </div>`;
      }
      const rawPct = Math.round(((b.val || 0) / b.goal) * 100);   // uncapped, for color
      const pct = Math.min(100, rawPct);                            // capped, for bar width
      // Semantic coloring: red = problem, green = good
      // moreIsBetter (protein, fiber): under = red, on/over target = green
      // lowerIsBetter (kcal, fats, carbs): over = red, on/under target = green
      let valColor;
      if (b.moreIsBetter) {
        valColor = rawPct >= 85 ? '#34c759' : rawPct >= 60 ? '#ff9500' : '#ff3b30';
      } else {
        valColor = rawPct <= 100 ? '#34c759' : rawPct <= 115 ? '#ff9500' : '#ff3b30';
      }
      return `<div class="bar-row">
            <span>${b.label}</span>
            <div class="bar-track"><div class="bar-fill ${b.cls}" style="width:${pct}%"></div></div>
            <span class="bar-value" style="color:${valColor}">${Math.round(b.val || 0)}<span> / ${b.goal}${b.unit}</span></span>
          </div>`;
    }).join('');
  }

  // Expose for later tasks
  window.__nutri = { state, API, loadDay, render, setDate };

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
      const favs = await API.getFavorites(15);
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
      await API.addItem({
        date: toISO(state.date),
        slot: activeSlot,
        name,
        weight,
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
    const res = await API.deleteItem({ meal_id: mealId, idx });
    const removed = res.removed;
    tg?.HapticFeedback?.impactOccurred?.('medium');
    showSnackbar(`Удалено: ${removed.name}`, async () => {
      // Undo: POST same product back to same slot
      const slot = el.closest('.slot')?.dataset.slot;
      await API.addItem({
        date: toISO(state.date),
        slot,
        name: removed.name,
        weight: removed.weight,
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
      await API.patchWeight({ meal_id: mealId, idx, weight: w });
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
