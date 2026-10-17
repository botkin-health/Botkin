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
  const SLOT_LABEL = { breakfast: 'Завтрак', lunch: 'Обед', snack: 'Перекусы', dinner: 'Ужин' };
  const SLOT_ICON = { breakfast: 'sunrise', lunch: 'sun', snack: 'apple', dinner: 'moon' };

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
        `<div class="load-error">Нет связи: ${e.message}</div>`;
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

  const icon = (name, cls = '') => `<svg class="ic ${cls}"><use href="#i-${name}"/></svg>`;

  const slotIcon = slot => `<span class="slot-ic" data-slot="${slot}">${icon(SLOT_ICON[slot])}</span>`;

  // Семантика цвета: протеин/клетчатка — «больше лучше», ккал/жиры/углеводы —
  // «не перебрать». Возвращает имя токена из theme.css.
  function macroTone(val, goal, moreIsBetter) {
    const pct = Math.round(((val || 0) / goal) * 100);
    if (moreIsBetter) return pct >= 85 ? 'ok' : pct >= 60 ? 'warn' : 'bad';
    return pct <= 100 ? 'ok' : pct <= 115 ? 'warn' : 'bad';
  }

  // Кольцо «осталось» — SVG, заполнение = съедено / цель.
  function ringSvg(fraction, tone) {
    const r = 46, c = 2 * Math.PI * r;
    const dash = Math.max(0, Math.min(1, fraction)) * c;
    return `<svg class="ring" viewBox="0 0 112 112" aria-hidden="true">
      <circle cx="56" cy="56" r="${r}" class="ring-track"/>
      <circle cx="56" cy="56" r="${r}" class="ring-fill tone-${tone}"
              stroke-dasharray="${dash.toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 56 56)"/>
    </svg>`;
  }

  function renderBudgetBanner() {
    const { totals_day: t, goals: g } = state.data;
    const banner = document.getElementById('budget-banner');
    if (!g || g.kcal == null) { banner.innerHTML = ''; return; }

    const consumed = Math.round(t.kcal || 0);
    const goal = Math.round(g.kcal);
    const diff = goal - consumed;
    const isOver = diff < 0;
    // Прошедший день с частичным Garmin-синком: цель оценочная (по среднему),
    // вердикт «перебор» по мусорным данным не выносим — нейтральный стиль и «≈».
    const incomplete = !!g.data_incomplete;
    const tone = incomplete ? 'warn' : isOver ? 'bad' : diff / goal < 0.15 ? 'warn' : 'ok';

    const heroNum = `${incomplete ? '≈' : ''}${Math.abs(diff)}`;
    const heroLabel = isOver ? 'перебор' : 'осталось';

    // Макросы — справа от кольца. Ккал уже в кольце, здесь не дублируем.
    const macros = [
      { label: 'Белки',     cls: 'p',   val: t.p,   goal: g.protein, more: true  },
      { label: 'Жиры',      cls: 'f',   val: t.f,   goal: g.fats,    more: false },
      { label: 'Углеводы',  cls: 'c',   val: t.c,   goal: g.carbs,   more: false },
      { label: 'Клетчатка', cls: 'fib', val: t.fib, goal: g.fiber,   more: true  },
    ];
    const macrosHtml = macros.map(m => {
      const v = Math.round(m.val || 0);
      if (m.goal == null) {
        return `<div class="macro-row"><div class="macro-head"><span>${m.label}</span><span class="macro-val">${v} г</span></div></div>`;
      }
      const pct = Math.min(100, Math.round((v / m.goal) * 100));
      const mt = macroTone(v, m.goal, m.more);
      return `<div class="macro-row">
        <div class="macro-head"><span>${m.label}</span><span class="macro-val"><b class="tone-${mt}">${v}</b> / ${m.goal} г</span></div>
        <div class="macro-track"><div class="macro-fill ${m.cls}" style="width:${pct}%"></div></div>
      </div>`;
    }).join('');

    // Строка расхода: БМР · активность (среднее за 14 дн. — входит в цель;
    // сегодняшнее — справочно, приглушено) · режим цели.
    const chips = [];
    if (g.bmr) chips.push(`${icon('flame')}БМР ${g.bmr}`);
    const actToday = g.activity_today;  // null, если за день нет синка часов
    const actAvg = g.activity_avg;       // среднее за 14 дней
    if (actAvg) chips.push(`${icon('bolt')}${actAvg} ср${actToday != null ? ` <span class="chip-dim">· ${actToday} сег</span>` : ''}`);
    else if (actToday != null) chips.push(`${icon('bolt')}<span class="chip-dim">${actToday} сег</span>`);
    const goalPct = g.deficit_pct ?? g.calorie_goal_pct;
    if (goalPct != null) {
      const mode = goalPct < 0 ? `дефицит ${Math.abs(goalPct)}%` : goalPct > 0 ? `профицит ${goalPct}%` : 'поддержание';
      chips.push(`${icon('target')}${mode}`);
    }
    // Источник цели (адаптивный TDEE) не выводим — деталь живёт в справке.

    const incompleteNote = incomplete
      ? `<div class="hero-note">${icon('alert')}Данные о расходе неполные — итог оценочный</div>` : '';

    banner.innerHTML = `
    <div class="hero-card">
      <div class="hero-main">
        <div class="ring-wrap">
          ${ringSvg(goal ? consumed / goal : 0, tone)}
          <div class="ring-center">
            <div class="ring-num tone-${tone}">${heroNum}</div>
            <div class="ring-label">${heroLabel}</div>
            <div class="ring-sub">${consumed} из ${incomplete ? '~' : ''}${goal}</div>
          </div>
        </div>
        <div class="macros">${macrosHtml}</div>
      </div>
      ${chips.length ? `<div class="hero-chips">${chips.map(c => `<span class="chip">${c}</span>`).join('')}</div>` : ''}
      ${incompleteNote}
    </div>`;
  }

  function renderSlots() {
    const container = document.getElementById('slots-container');
    const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner'];
    // Group meals by slot
    const bySlot = { breakfast: [], lunch: [], snack: [], dinner: [] };
    for (const m of state.data.meals) bySlot[m.slot]?.push(m);

    // Empty-state hint: when the day has no meals yet, show a CTA that explains
    // how to log food (since the mini-app itself doesn't accept food input —
    // bot's chat does). Without this banner new users get stuck (see Лена 16.05.2026).
    const emptyHint = (state.data.meals.length === 0) ? `
      <div class="empty-hint">
        <div class="empty-hint-title">Запиши еду в чате</div>
        <div class="empty-hint-body">Бот понимает три формата:</div>
        <ul class="empty-hint-list">
          <li>${icon('message')}<span><b>Текст</b> — «овсянка 100г, кофе с молоком»</span></li>
          <li>${icon('camera')}<span><b>Фото</b> — тарелки или упаковки</span></li>
          <li>${icon('bell')}<span><b>Голос</b> — наговори голосовое</span></li>
        </ul>
        <div class="empty-hint-foot">Дневник заполнится автоматически.</div>
      </div>` : '';

    container.innerHTML = `${emptyHint}<div class="slots-section">${SLOTS.map(slot => {
      const meals = bySlot[slot];
      if (meals.length === 0) {
        return `
        <div class="slot dim" data-slot="${slot}">
          <div class="slot-left">
            <div class="slot-title">${slotIcon(slot)}${SLOT_LABEL[slot]}</div>
            <div class="slot-empty">Пока пусто — пришлите фото или текст в чат</div>
          </div>
          <div class="slot-right">
            <span class="slot-meta slot-meta-empty">—</span>
          </div>
        </div>`;
      }
      // Merge all meals in this slot into one card (items from each preserve their meal_id).
      const expandedKey = `exp:slot:${slot}`;
      const isExpanded = sessionStorage.getItem(expandedKey) === '1';
            const totalKcal = meals.reduce((s, m) => s + (m.totals.kcal || 0), 0);
      const totalFib  = meals.reduce((s, m) => s + (m.totals.fib  || 0), 0);
      const allItems = meals.flatMap(m => m.items);
      const previewText = allItems.map(it => it.name).join(' · ');
      const itemsHtml = isExpanded ? renderMergedItems(slot, meals) : '';
      const hasPlan = meals.some(m => m.status === 'plan');
      const planBadge = hasPlan ? `<span class="badge-plan">${icon('clipboard')}план</span>` : '';
      return `
        <div class="slot ${isExpanded ? 'expanded' : ''}" data-slot="${slot}">
          <div class="slot-header-row" data-toggle="slot:${slot}">
            <div class="slot-left">
              <div class="slot-title">${slotIcon(slot)}${SLOT_LABEL[slot]}${planBadge}</div>
              ${!isExpanded ? `<div class="slot-preview">${escapeHtml(previewText)}</div>` : ''}
            </div>
            <div class="slot-right">
              <div class="slot-meta">${Math.round(totalKcal)}<span class="slot-unit">ккал</span></div>
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
    container.querySelectorAll('.plan-close').forEach(el => {
      el.addEventListener('click', async (e) => {
        e.stopPropagation();
        const mealId = Number(el.dataset.mealId);
        try {
          await API.patchMealStatus(mealId, 'eaten');
          tg?.HapticFeedback?.notificationOccurred?.('success');
          await loadDay();
        } catch (err) {
          tg?.showAlert?.(`Ошибка: ${err.message}`) ?? alert(err.message);
        }
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
      const warn = noMacros ? `<span class="item-warn">${icon('alert')}</span> ` : '';
      const planCls = meal.status === 'plan' ? ' item-plan' : '';
      return `
      <div class="item${planCls}" data-meal-id="${meal.id}" data-idx="${it.idx}">
        <div class="delete-bg">Удалить</div>
        <div class="item-row">
          <div class="item-name">${warn}${escapeHtml(it.name)}</div>
          <div class="item-kcal">${Math.round(it.kcal)}<span class="slot-unit">ккал</span></div>
          <div class="item-macros">${Math.round(it.weight)} г · Б <b>${it.p}</b> · Ж <b>${it.f}</b> · У <b>${it.c}</b> · Кл <b>${it.fib}</b></div>
        </div>
      </div>`;
    }).join('');
    const planMeals = meals.filter(m => m.status === 'plan');
    const planCloseHtml = planMeals.map(m => `
      <div class="plan-close" data-meal-id="${m.id}">${icon('check')}Съедено целиком — закрыть план</div>`).join('');
    return `
    <div class="items">
      ${itemsHtml}
      ${planCloseHtml}
      <div class="add-in-slot" data-slot="${slot}">${icon('plus')}Добавить в ${SLOT_LABEL[slot].toLowerCase()}</div>
    </div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // Прогресс БЖУ переехал в карточку-шапку (renderBudgetBanner) — подвал скрыт.
  function renderFooter() {
    const footer = document.getElementById('day-footer');
    if (footer) footer.hidden = true;
  }

  // Expose for later tasks
  window.__nutri = { state, API, loadDay, render, setDate };

  let activeSlot = null;

  async function openAddSheet(slot) {
    activeSlot = slot;
    document.getElementById('add-sheet-title').textContent =
      `Добавить: ${SLOT_LABEL[slot].toLowerCase()}`;
    document.getElementById('add-sheet').classList.add('open');
    document.getElementById('add-name').value = '';
    document.getElementById('add-weight').value = '';
    document.getElementById('fav-list').innerHTML = '<div class="fav-hint">Загружаем…</div>';
    try {
      const favs = await API.getFavorites(15);
      document.getElementById('fav-list').innerHTML = favs.length
        ? favs.map(f => `
            <button class="fav-chip" data-name="${escapeHtml(f.name)}" data-weight="${f.default_weight}">
              ${escapeHtml(f.name)}
              <span class="w">${Math.round(f.default_weight)} г</span>
            </button>`).join('')
        : '<div class="fav-hint">Пока пусто</div>';
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

  // Sync timezone from browser on every open — fire-and-forget, never blocks UI.
  // Uses IANA name (e.g. "Asia/Jerusalem") which handles DST automatically.
  (function () {
    try {
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) API.patchTimezone(tz).catch(function () {});
    } catch (_) {}
  })();

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
      el.classList.toggle('swiping', currentX < 0);
    }, { passive: true });
    el.addEventListener('touchend', async () => {
      dragging = false;
      if (currentX < -60) {
        await deleteItem(el);
      } else {
        row.style.transform = '';
        el.classList.remove('swiping');
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
  document.getElementById('edit-delete').onclick = async () => {
    document.getElementById('edit-sheet').classList.remove('open');
    await deleteItem(el);
  };
}

document.getElementById('edit-sheet-close').addEventListener('click', () =>
  document.getElementById('edit-sheet').classList.remove('open')
);
document.getElementById('edit-sheet').addEventListener('click', (e) => {
  if (e.target.id === 'edit-sheet') e.target.classList.remove('open');
});
})();
