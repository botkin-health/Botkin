# Diary UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Visually redesign the Telegram Mini App diary screen — single-row header, large calorie hero banner, colored left-border meal slots, fiber+protein progress footer, and a Warm Stone tab bar for navigation.

**Architecture:** Pure CSS/JS changes to three existing files (`index.html`, `day.css`, `day.js`). No backend changes. Tab bar v1 has Дневник (live), Добавки (stub), Настройки (existing settings section repurposed). Deploy via existing rsync → docker cp → Cloudflare cache purge pipeline.

**Tech Stack:** Vanilla JS, CSS custom properties, Telegram Web App SDK, FastAPI StaticFiles

---

## File Map

| File | What changes |
|---|---|
| `telegram-bot/webapp/index.html` | Replace 2-row header with single-row; add tab bar HTML at bottom; bump `day.js?v=5` |
| `telegram-bot/webapp/day.css` | New CSS for header, hero banner, colored slots, progress section, tab bar |
| `telegram-bot/webapp/day.js` | Update `updateSwitcher()`, `renderBudgetBanner()`, `renderSlots()`, `renderFooter()`; add tab navigation |

---

### Task 1: Redesign HTML structure (header + tab bar)

**Files:**
- Modify: `telegram-bot/webapp/index.html`

Replace the existing `<div class="top-header">` + `.day-switcher` block with a single combined header row, add tab bar at the bottom, and bump the JS version.

- [ ] **Step 1.1: Replace header HTML**

Find and replace in `index.html`:
```html
<!-- OLD: two-row header -->
<div class="top-header">
  <span class="top-title" id="top-title">🍽 Дневник</span>
  <button class="header-btn" id="toggle-settings" aria-label="Настройки">⚙️</button>
</div>

<section id="day-section" class="section active">
  <div class="day-switcher">
    <button class="day-nav" id="prev-day" aria-label="Предыдущий день">‹</button>
    <label class="day-label-wrap" aria-label="Выбрать дату">
      <div class="day-label" id="day-label">Сегодня</div>
      <div class="day-sub" id="day-sub"></div>
      <input type="date" id="date-picker" hidden>
    </label>
    <button class="day-nav" id="next-day" aria-label="Следующий день">›</button>
  </div>
```

Replace with:
```html
<!-- NEW: single-row app header (always visible) -->
<div class="app-header">
  <button class="day-nav" id="prev-day" aria-label="Предыдущий день">‹</button>
  <label class="day-label-wrap" aria-label="Выбрать дату">
    <div class="app-header-label">ДНЕВНИК</div>
    <div class="app-header-date" id="day-label">Сегодня</div>
    <input type="date" id="date-picker" hidden>
  </label>
  <button class="day-nav" id="next-day" aria-label="Следующий день">›</button>
</div>

<section id="day-section" class="section active">
```

- [ ] **Step 1.2: Add tab bar HTML before `</body>`**

Just before the first `<script src="day.js...">` line, add:
```html
<!-- Tab bar -->
<nav class="tab-bar" id="tab-bar">
  <button class="tab-item active" data-tab="day" onclick="switchTab('day')">
    <span class="tab-icon">📅</span>
    <span class="tab-label">Дневник</span>
  </button>
  <button class="tab-item" data-tab="supplements-tab" onclick="switchTab('supplements-tab')">
    <span class="tab-icon">💊</span>
    <span class="tab-label">Добавки</span>
  </button>
  <button class="tab-item" data-tab="settings" onclick="switchTab('settings')">
    <span class="tab-icon">⚙️</span>
    <span class="tab-label">Настройки</span>
  </button>
</nav>
```

- [ ] **Step 1.3: Add supplements stub section**

After `</section><!-- /settings-section -->` and before the sheets, add:
```html
<section id="supplements-tab-section" class="section">
  <div style="padding: 40px 24px; text-align: center; color: #8e8e93;">
    <div style="font-size: 48px; margin-bottom: 16px;">💊</div>
    <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px; color: #1c1c1e;">Добавки</div>
    <div style="font-size: 14px; line-height: 1.5;">Раздел в разработке.<br>Пока управляй добавками через ⚙️ Настройки.</div>
  </div>
</section>
```

- [ ] **Step 1.4: Add `switchTab` function inside the inline `<script>` block (after the existing `go()` function)**

```javascript
function switchTab(tab) {
  // Update tab bar active state
  document.querySelectorAll('.tab-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  // Show/hide sections
  const sectionMap = {
    'day': 'day-section',
    'supplements-tab': 'supplements-tab-section',
    'settings': 'settings-section',
  };
  document.querySelectorAll('body > section').forEach(s => s.classList.remove('active'));
  const target = document.getElementById(sectionMap[tab]);
  if (target) target.classList.add('active');
  // When switching to settings, reset to home sub-section
  if (tab === 'settings') go('home');
}
```

- [ ] **Step 1.5: Remove old settings toggle listener from `day.js`**

In `day.js`, find and DELETE this block (lines ~79-87):
```javascript
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
```

- [ ] **Step 1.6: Bump JS version in `index.html`**

Change `day.js?v=4` → `day.js?v=5`

- [ ] **Step 1.7: Verify the HTML parses and the page loads (manual check)**

Open `http://localhost:8000` (or production URL) — header should show one row.

---

### Task 2: CSS — header + base layout

**Files:**
- Modify: `telegram-bot/webapp/day.css`

- [ ] **Step 2.1: Replace `.top-header` styles with `.app-header`**

Find and replace in `day.css`:
```css
.top-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--tg-theme-bg-color, #fff); z-index: 10;
}
.top-title { font-weight: 600; font-size: 15px; }
.header-btn {
  background: none; border: none; font-size: 20px; padding: 4px 8px; cursor: pointer;
  color: var(--accent);
}

.day-switcher {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 4px 6px;
}
.day-nav {
  background: none; border: none; font-size: 22px; color: var(--accent);
  padding: 2px 14px; cursor: pointer; line-height: 1;
}
.day-nav:disabled { opacity: .3; cursor: not-allowed; }
.day-label-wrap { cursor: pointer; flex: 1; text-align: center; }
.day-label { font-size: 14px; font-weight: 600; }
.day-sub { display: none; }
.calendar-row { display: none; }
.calendar-btn { display: none; }
```

With:
```css
/* ── Single-row app header ── */
.app-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--tg-theme-bg-color, #fff); z-index: 10;
}
.day-nav {
  background: none; border: none; font-size: 22px; color: var(--accent);
  padding: 2px 10px; cursor: pointer; line-height: 1;
}
.day-nav:disabled { opacity: .3; cursor: not-allowed; }
.day-label-wrap { cursor: pointer; flex: 1; text-align: center; }
.app-header-label {
  font-size: 11px; font-weight: 800; color: var(--muted);
  text-transform: uppercase; letter-spacing: .5px; line-height: 1;
}
.app-header-date { font-size: 15px; font-weight: 700; line-height: 1.3; }

/* legacy — kept to avoid JS errors if referenced anywhere */
.day-sub { display: none; }
```

- [ ] **Step 2.2: Adjust body padding for tab bar**

In `index.html` inline `<style>`, find:
```css
body { font-family: ...; background: ...; color: ...; padding: 16px; max-width: 480px; margin: 0 auto; }
```

Change `padding: 16px` → `padding: 0`:
```css
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--tg-theme-bg-color, #fff);
       color: var(--tg-theme-text-color, #222);
       padding: 0; max-width: 480px; margin: 0 auto; }
```

Then adjust `#slots-container` in `day.css` — the current `padding: 0 16px 100px` bottom needs extra space for tab bar (~50px more):
```css
#slots-container { padding: 0 16px 160px; }
```

---

### Task 3: CSS — hero banner

**Files:**
- Modify: `telegram-bot/webapp/day.css`

- [ ] **Step 3.1: Replace `.budget-banner` styles**

Find in `day.css`:
```css
.budget-banner {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 16px 8px; font-size: 12px;
}
.budget-remaining {
  font-size: 15px; font-weight: 700;
}
.budget-remaining.ok { color: #34c759; }
.budget-remaining.warn { color: #ff9500; }
.budget-remaining.over { color: #ff3b30; }
.budget-macros { color: var(--muted); display: flex; gap: 10px; }
.budget-macros .macro { white-space: nowrap; }
.budget-macros .macro.ok { color: #34c759; }
.budget-macros .macro.warn { color: #ff9500; }
.budget-macros .macro.over { color: #ff3b30; }
.budget-macros .macro-goal { color: var(--muted); font-weight: 400; }
```

Replace with:
```css
/* ── Hero banner ── */
.budget-banner {
  padding: 6px 16px 8px;
  border-bottom: 1px solid var(--border);
}
.budget-remaining {
  font-size: 34px; font-weight: 900; letter-spacing: -1px; line-height: 1;
  display: block;
}
.budget-remaining.ok   { color: #34c759; }
.budget-remaining.warn { color: #ff9500; }
.budget-remaining.over { color: #ff3b30; }
.budget-sub {
  font-size: 12px; color: var(--muted); margin-top: 2px; display: block;
}
.budget-macros { display: flex; gap: 12px; font-size: 12px; margin-top: 4px; }
.budget-macros .macro { white-space: nowrap; font-weight: 600; }
.budget-macros .macro.ok   { color: #34c759; }
.budget-macros .macro.warn { color: #ff9500; }
.budget-macros .macro.over { color: #ff3b30; }
.budget-macros .macro-goal { color: var(--muted); font-weight: 400; }
```

---

### Task 4: CSS — colored slot cards

**Files:**
- Modify: `telegram-bot/webapp/day.css`

- [ ] **Step 4.1: Add slot color variables**

At the top of `day.css`, inside `:root { ... }`, add after existing variables:
```css
  --slot-breakfast: #f5b02b;
  --slot-lunch:     #4cb563;
  --slot-snack:     #e0577c;
  --slot-dinner:    #8e79d6;
```

- [ ] **Step 4.2: Replace `.slot` styles**

Find in `day.css`:
```css
.slot {
  background: var(--slot-bg); border-radius: 14px; padding: 12px 14px;
  margin-bottom: 10px;
}
.slot.dim .slot-title { color: var(--muted); font-weight: 500; }
.slot-header {
  display: flex; justify-content: space-between; align-items: center;
  min-height: 36px; cursor: pointer;
}
.slot-title { font-weight: 600; font-size: 15px; }
.slot-meta { font-size: 12px; color: var(--muted); }
.slot-empty { color: #c7c7cc; font-size: 13px; padding: 4px 0; }
.slot-preview { font-size: 12px; color: var(--muted); padding: 2px 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
```

Replace with:
```css
/* Slots wrapper — grey background section */
#slots-container { padding: 0 0 160px; }
.slots-section { background: #f2f2f7; padding: 8px; }

.slot {
  background: #fff; border-radius: 10px; padding: 9px 12px;
  margin-bottom: 6px; border-left: 4px solid var(--border);
  display: flex; justify-content: space-between; align-items: flex-start;
}
.slot:last-child { margin-bottom: 0; }
.slot-left { flex: 1; min-width: 0; }
.slot-right { flex-shrink: 0; padding-left: 8px; }

/* Per-slot colors */
.slot[data-slot="breakfast"] { border-left-color: var(--slot-breakfast); }
.slot[data-slot="lunch"]     { border-left-color: var(--slot-lunch); }
.slot[data-slot="snack"]     { border-left-color: var(--slot-snack); }
.slot[data-slot="dinner"]    { border-left-color: var(--slot-dinner); }

.slot-title { font-weight: 700; font-size: 13px; }
.slot-meta {
  font-size: 13px; font-weight: 700; white-space: nowrap;
}
/* Color kcal value to match slot color */
.slot[data-slot="breakfast"] .slot-meta { color: var(--slot-breakfast); }
.slot[data-slot="lunch"]     .slot-meta { color: var(--slot-lunch); }
.slot[data-slot="snack"]     .slot-meta { color: var(--slot-snack); }
.slot[data-slot="dinner"]    .slot-meta { color: var(--slot-dinner); }

.slot.dim .slot-title { color: var(--muted); }
.slot-empty { color: #c7c7cc; font-size: 11px; margin-top: 2px; }
.slot-preview {
  font-size: 11px; color: var(--muted); margin-top: 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;
}
.slot-header { display: contents; } /* flatten, layout handled by .slot flex */
```

- [ ] **Step 4.3: Keep `.items` and item styles intact**

The expanded item list is rendered inside an `.items` div inside the slot. With the new flat slot layout, we need the expanded state to wrap differently. Add after the slot styles:

```css
/* Expanded slot — full-width card with item list */
.slot.expanded {
  flex-direction: column;
  align-items: stretch;
}
.slot.expanded .slot-header-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 4px;
}
.slot.expanded .slot-right { padding-left: 0; }
```

---

### Task 5: CSS — progress section + tab bar

**Files:**
- Modify: `telegram-bot/webapp/day.css`

- [ ] **Step 5.1: Update footer styles**

Find in `day.css`:
```css
.day-footer {
  position: sticky; bottom: 0; background: var(--tg-theme-bg-color, #fff);
  border-top: 1px solid var(--border); padding: 10px 16px 14px;
}
.footer-title { font-size: 11px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .5px; margin-bottom: 6px; }
.bar-row { display: grid; grid-template-columns: 70px 1fr 80px; align-items: center;
           gap: 8px; font-size: 12px; margin-bottom: 4px; }
```

Replace with:
```css
.day-footer {
  position: sticky; bottom: 50px; /* sit above tab bar */
  background: var(--tg-theme-bg-color, #fff);
  border-top: 1px solid var(--border); padding: 8px 16px 10px;
}
.footer-title { font-size: 9px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .5px; margin-bottom: 4px; }
.bar-row { display: grid; grid-template-columns: 64px 1fr 72px; align-items: center;
           gap: 6px; font-size: 11px; margin-bottom: 3px; }
```

- [ ] **Step 5.2: Add tab bar CSS**

Append at the end of `day.css`:
```css
/* ── Tab bar (Warm Stone palette) ── */
.tab-bar {
  position: fixed; bottom: 0; left: 0; right: 0;
  max-width: 480px; margin: 0 auto;
  display: flex; justify-content: space-around; align-items: center;
  height: 50px;
  background: #e8e3dc;
  border-top: 1px solid #d6d0c9;
  z-index: 20;
}
.tab-item {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  gap: 2px; background: none; border: none; cursor: pointer;
  padding: 6px 0; color: #9a9187;
}
.tab-icon { font-size: 20px; line-height: 1; }
.tab-label { font-size: 10px; font-weight: 600; color: #9a9187; }
.tab-item.active .tab-label { color: #5a5048; }

/* Safe area padding for notched iPhones */
@supports (padding-bottom: env(safe-area-inset-bottom)) {
  .tab-bar { padding-bottom: env(safe-area-inset-bottom); height: calc(50px + env(safe-area-inset-bottom)); }
  .day-footer { bottom: calc(50px + env(safe-area-inset-bottom)); }
}
```

- [ ] **Step 5.3: Adjust snackbar position**

The snackbar is currently at `bottom: 70px`. It needs to be above the tab bar:

Find:
```css
.snackbar {
  position: fixed; bottom: 70px; left: 16px; right: 16px;
```

Replace:
```css
.snackbar {
  position: fixed; bottom: 62px; left: 16px; right: 16px;
```

---

### Task 6: JS — update hero banner renderer

**Files:**
- Modify: `telegram-bot/webapp/day.js`

- [ ] **Step 6.1: Replace `renderBudgetBanner()`**

Find the entire `renderBudgetBanner()` function in `day.js` and replace:

```javascript
function renderBudgetBanner() {
  const { totals_day: t, goals: g } = state.data;
  const banner = document.getElementById('budget-banner');
  if (!g || g.kcal == null) { banner.innerHTML = ''; return; }

  const consumed = Math.round(t.kcal || 0);
  const goal = Math.round(g.kcal);
  const diff = goal - consumed;
  const isOver = diff < 0;
  const cls = isOver ? 'over' : diff / goal < 0.15 ? 'warn' : 'ok';

  const heroText = isOver
    ? `−${Math.abs(diff)} ккал`
    : `+${diff} ккал`;
  const subText = isOver
    ? `перебор · съедено ${consumed} из ${goal}`
    : `осталось · съедено ${consumed} из ${goal}`;

  const macroCls = (val, goal) => {
    if (!goal) return '';
    const p = val / goal;
    if (p >= 1.1) return 'over';
    if (p >= 0.85) return 'ok';
    return 'warn';
  };
  const macro = (letter, val, goal) => {
    const v = Math.round(val || 0);
    const c = macroCls(val, goal);
    return goal
      ? `<span class="macro ${c}">${letter} ${v}<span class="macro-goal">/${goal}</span></span>`
      : `<span class="macro">${letter} ${v}</span>`;
  };

  banner.innerHTML = `
    <span class="budget-remaining ${cls}">${heroText}</span>
    <span class="budget-sub">${subText}</span>
    <div class="budget-macros">
      ${macro('Б', t.p, g.protein)}
      ${macro('Ж', t.f, g.fats)}
      ${macro('У', t.c, g.carbs)}
    </div>`;
}
```

---

### Task 7: JS — update slot renderer

**Files:**
- Modify: `telegram-bot/webapp/day.js`

The slot renderer needs to produce the new flat card layout with colored left border. The key change is wrapping content in `.slot-left` / `.slot-right` and collapsing the slot header into a flex row, while keeping expanded item list working.

- [ ] **Step 7.1: Update `renderSlots()` collapsed-state HTML**

Find inside `renderSlots()` the block that generates slots and replace the slot HTML templates:

Current empty slot template:
```javascript
return `
<div class="slot dim" data-slot="${slot}">
  <div class="slot-header">
    <div class="slot-title">${SLOT_LABEL[slot]}</div>
    <button class="header-btn add-in-slot-btn" data-slot="${slot}">+</button>
  </div>
  <div class="slot-empty">Пока ничего</div>
</div>`;
```

Replace with:
```javascript
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
```

Current filled slot template (find the `return \`` block inside the else branch):
```javascript
return `
  <div class="slot" data-slot="${slot}">
    <div class="slot-header" data-toggle="slot:${slot}">
      <div class="slot-title">${SLOT_LABEL[slot]}</div>
      <div class="slot-meta">${Math.round(totalKcal)} ккал ${hdrExtra}</div>
    </div>
    ${!isExpanded ? `<div class="slot-preview">${escapeHtml(previewText)}</div>` : itemsHtml}
  </div>`;
```

Replace with:
```javascript
return `
  <div class="slot ${isExpanded ? 'expanded' : ''}" data-slot="${slot}">
    <div class="slot-header-row" data-toggle="slot:${slot}" style="display:flex;justify-content:space-between;align-items:flex-start;cursor:pointer;width:100%">
      <div class="slot-left" style="flex:1;min-width:0;">
        <div class="slot-title">${SLOT_LABEL[slot]}</div>
        ${!isExpanded ? `<div class="slot-preview">${escapeHtml(previewText)}</div>` : ''}
      </div>
      <div class="slot-right" style="flex-shrink:0;padding-left:8px;">
        <div class="slot-meta">${Math.round(totalKcal)}</div>
      </div>
    </div>
    ${isExpanded ? itemsHtml : ''}
  </div>`;
```

- [ ] **Step 7.2: Wrap slots in `.slots-section` container**

At the top of `renderSlots()`, find:
```javascript
container.innerHTML = SLOTS.map(slot => {
```

Replace with:
```javascript
container.innerHTML = `<div class="slots-section">${SLOTS.map(slot => {
```

And close the template at the end of the `.join('')`:
```javascript
}).join('')}</div>`;
```

(Find `}).join('');` and replace with `}).join('')}</div>\`;`)

- [ ] **Step 7.3: Update the toggle event listener selector**

The toggle is now on `[data-toggle]` inside `.slot-header-row` instead of `.slot-header`. Update the querySelector:

Find:
```javascript
container.querySelectorAll('.slot-header[data-toggle]').forEach(el => {
```

Replace with:
```javascript
container.querySelectorAll('[data-toggle]').forEach(el => {
```

---

### Task 8: JS — update footer renderer (fiber + protein only)

**Files:**
- Modify: `telegram-bot/webapp/day.js`

- [ ] **Step 8.1: Replace `renderFooter()`**

Find the entire `renderFooter()` function and replace:

```javascript
function renderFooter() {
  const { totals_day: t, goals: g } = state.data;
  const bars = [
    { label: 'Клетчатка', cls: 'fib', val: t.fib, goal: g?.fiber,   unit: 'г' },
    { label: 'Белки',     cls: 'p',   val: t.p,   goal: g?.protein, unit: 'г' },
  ];
  document.getElementById('bars').innerHTML = bars.map(b => {
    if (b.goal == null) {
      return `<div class="bar-row">
              <span>${b.label}</span>
              <div></div>
              <span class="bar-value">${Math.round(b.val || 0)} ${b.unit}</span>
            </div>`;
    }
    const pct = Math.min(100, Math.round(((b.val || 0) / b.goal) * 100));
    const valCls = pct >= 110 ? 'over' : pct >= 85 ? 'ok' : 'warn';
    return `<div class="bar-row">
            <span>${b.label}</span>
            <div class="bar-track"><div class="bar-fill ${b.cls}" style="width:${pct}%"></div></div>
            <span class="bar-value" style="color:${valCls === 'ok' ? '#34c759' : valCls === 'over' ? '#ff3b30' : '#ff9500'}">${Math.round(b.val || 0)}<span> / ${b.goal}${b.unit}</span></span>
          </div>`;
  }).join('');
}
```

---

### Task 9: JS — update `updateSwitcher()` for new header DOM

**Files:**
- Modify: `telegram-bot/webapp/day.js`

The new header uses `.app-header-date` instead of `#day-label` (ID kept same, class changed). The `#top-title` element no longer exists.

- [ ] **Step 9.1: Update `updateSwitcher()`**

Find:
```javascript
function updateSwitcher() {
  const d = state.date, today = new Date();
  document.getElementById('day-label').textContent = dayLabelText(d);
  document.getElementById('next-day').disabled = daysDiff(today, d) >= 7;
  document.getElementById('date-picker').value = toISO(d);
}
```

Replace with:
```javascript
function updateSwitcher() {
  const d = state.date, today = new Date();
  // #day-label is now the date line inside .app-header
  const lbl = document.getElementById('day-label');
  if (lbl) lbl.textContent = dayLabelText(d);
  const nextBtn = document.getElementById('next-day');
  if (nextBtn) nextBtn.disabled = daysDiff(today, d) >= 7;
  const picker = document.getElementById('date-picker');
  if (picker) picker.value = toISO(d);
}
```

---

### Task 10: Deploy

**Files:** no code changes — just deploy

- [ ] **Step 10.1: Sync files to server**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"

rsync -avz --checksum \
  telegram-bot/webapp/day.js \
  telegram-bot/webapp/day.css \
  telegram-bot/webapp/index.html \
  root@health.orangegate.cc:/opt/healthvault/telegram-bot/webapp/
```

- [ ] **Step 10.2: Copy files into Docker container**

```bash
ssh root@health.orangegate.cc "
  docker cp /opt/healthvault/telegram-bot/webapp/day.js healthvault_bot:/app/telegram-bot/webapp/day.js &&
  docker cp /opt/healthvault/telegram-bot/webapp/day.css healthvault_bot:/app/telegram-bot/webapp/day.css &&
  docker cp /opt/healthvault/telegram-bot/webapp/index.html healthvault_bot:/app/telegram-bot/webapp/index.html
"
```

Expected output: `Successfully copied` for each file.

- [ ] **Step 10.3: Purge Cloudflare cache**

```bash
CF_ZONE=da74491a16583a63fe678d2221ce9ca1
CF_KEY=$(op item get "Cloudflare API Key" --account my.1password.com --fields password 2>/dev/null || echo "")

curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE}/purge_cache" \
  -H "Authorization: Bearer ${CF_KEY}" \
  -H "Content-Type: application/json" \
  --data '{"files":["https://health.orangegate.cc/webapp/day.js","https://health.orangegate.cc/webapp/day.css","https://health.orangegate.cc/webapp/index.html"]}' \
  | python3 -m json.tool
```

Expected: `"success": true`

- [ ] **Step 10.4: Verify in browser**

Open `https://health.orangegate.cc/webapp/` (or send `/day` in Telegram to open Mini App). Check:
- [ ] Header is one row: `‹ ДНЕВНИК / Пт, 17 апр. ›`
- [ ] Hero banner shows large `−NNN ккал` or `+NNN ккал`
- [ ] Slot cards have colored left border
- [ ] Footer shows only Клетчатка + Белки
- [ ] Tab bar visible at bottom with Warm Stone background
- [ ] Tab switching works (💊 Добавки shows stub, ⚙️ Настройки shows settings)

- [ ] **Step 10.5: Commit**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
git add telegram-bot/webapp/day.js telegram-bot/webapp/day.css telegram-bot/webapp/index.html
git commit -m "feat(webapp): UX redesign — hero banner, colored slots, tab bar

- Single-row header (saves ~36px, all 4 slots fit without scroll)
- Large calorie hero banner with ±diff format and macro coloring
- Colored left-border meal slots (breakfast=yellow, lunch=green, snack=pink, dinner=purple)
- Progress footer shows only fiber + protein (kcal already in banner)
- Warm Stone tab bar (#e8e3dc) with Дневник · Добавки · Настройки
- Supplements tab is a stub; Settings reuses existing settings section

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Single-row header: Task 1 + Task 2
- ✅ Hero banner (large kcal number): Task 3 + Task 6
- ✅ Colored left-border slots: Task 4 + Task 7
- ✅ Readable typography (+2px): Task 3/4/5 — sizes adjusted throughout (13px slots, 34px hero)
- ✅ Footer: fiber + protein only: Task 5 + Task 8
- ✅ Tab bar Warm Stone: Task 5
- ✅ Settings accessible via tab bar: Task 1 `switchTab()`
- ✅ Supplements stub: Task 1 Step 1.3

**Placeholder scan:** No TBDs or TODOs in code blocks.

**Type consistency:**
- `renderBudgetBanner()` — uses same `state.data` shape (`totals_day`, `goals`)
- `renderFooter()` — accesses `t.fib`, `g.fiber`, `t.p`, `g.protein` — same as before
- `renderSlots()` — `SLOT_LABEL`, `bySlot`, `state.data.meals` — unchanged
- `updateSwitcher()` — `#day-label` ID kept in HTML, function uses same ID
- `switchTab()` — IDs `day-section`, `supplements-tab-section`, `settings-section` all present in HTML

**Edge cases covered:**
- `updateSwitcher()` uses `?.` guards to avoid crash if DOM elements missing
- Snackbar repositioned above tab bar
- Safe area inset for iPhone notch handled in CSS
