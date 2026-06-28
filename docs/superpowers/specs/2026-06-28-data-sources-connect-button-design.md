# Дизайн: кнопка «Подключить» для источников данных в mini-app

**Дата:** 2026-06-28  
**Контекст:** PR #150 добавил секцию «Источники данных» в mini-app настройки. У неподключённых источников нужна кнопка «Подключить», ведущая пользователя к подключению.

---

## Контекст и текущее состояние

Секция «Источники данных» в `telegram-bot/webapp/settings.js` рендерит строки через `_renderSourceRow(s)`. Данные приходят с `/api/profile/data_sources` (`telegram-bot/webhook/profile_api.py`).

Текущие источники и их пути подключения:

| Источник | Существующий flow подключения | Файл |
|----------|-------------------------------|------|
| Apple Health (iOS) | `/health_token` → выбор HAE ($24.99) vs iOS Shortcuts → инструкция с токеном | `handlers/apple_health_connect.py` |
| Google Health Connect (Android) | Тот же `health_token` + APK `mcnaveen/health-connect-webhook` + эндпоинт `/android_health_v1` | `webhook/android_health.py` |
| LibreLink CGM | `/connect_cgm` → пригласить `dr@botkin.health` → бот ждёт 10 мин и ловит автоматически | `handlers/connect_cgm.py` |
| Garmin | Server-side cron с hardcoded credentials — нет пользовательского пути | — |
| Zepp / Mi Scale | OAuth через `zepp_api.py --reauth` — нет пользовательского пути | — |
| Netatmo | refresh_token в `.env` — нет пользовательского пути | — |

---

## Решение: expand-in-place (аккордеон)

Кнопка «Подключить ›» у каждого неподключённого источника разворачивает `.connect-panel` прямо под строкой. Одновременно открыта только одна панель. Пользователь не уходит из mini-app (кроме CGM, где polling-часть делегируется боту).

### UI-структура строки

```
┌─────────────────────────────────────────────┐
│ ⌚ Garmin          не подключён  [Подключить ›] │
├─────────────────────────────────────────────┤  ← разворачивается при клике
│  📋 Поддержка подключения Garmin            │
│  появится в следующем обновлении.           │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 🍎 Apple Health    не подключён  [Подключить ›] │
├─────────────────────────────────────────────┤
│  Выбери способ:                             │
│  [💰 Health Auto Export]  [🆓 Shortcuts]    │
│  (после выбора — шаги + токен + кнопка копирования) │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 🩸 LibreLink (CGM) не подключён  [Подключить ›] │
├─────────────────────────────────────────────┤
│  1. Открой FreeStyle Libre 3 → LibreLinkUp  │
│  2. Invite Follower → dr@botkin.health      │
│  [Запустить ожидание в боте →]              │  ← tg:// deeplink
└─────────────────────────────────────────────┘
```

---

## Backend: изменения в `/api/profile/data_sources`

### Новые поля в ответе

Каждый объект источника получает поле `connect_info`:

```json
{
  "id": "apple_health",
  "name": "Apple Health",
  "icon": "🍎",
  "connected": false,
  "last_updated": null,
  "connect_info": {
    "flow": "inline_token",
    "health_token": "hvt_abc123"
  }
}
```

### Типы flow

| flow | Источники | Что рендерит фронтенд |
|------|-----------|-----------------------|
| `inline_token` | Apple Health, Health Connect | Шаги + токен с кнопкой «Скопировать» |
| `tg_deeplink` | CGM | Шаги + кнопка → `tg://resolve?domain=Botkin_md_bot&start=connect_cgm` |
| `coming_soon` | Garmin, Zepp, Netatmo | Плашка «Поддержка появится в следующем обновлении» |

### Правила для `health_token`

- Возвращается только когда `connected=False` и `flow="inline_token"`
- Генерируется через существующую `get_or_create_health_token()` (тот же токен что `/health_token` в боте)
- `null` во всех остальных случаях (не утекает без нужды)

### Реализация в `profile_api.py`

Логика `connect_info` строится вместе с остальными данными в `get_data_sources()`:

```python
_CONNECT_INFO = {
    "garmin":         {"flow": "coming_soon"},
    "apple_health":   {"flow": "inline_token"},
    "health_connect": {"flow": "inline_token"},
    "zepp":           {"flow": "coming_soon"},
    "netatmo":        {"flow": "coming_soon"},
    "cgm":            {"flow": "tg_deeplink", "deeplink": "tg://resolve?domain=Botkin_md_bot&start=connect_cgm"},
}

# При построении ответа:
# - для inline_token + connected=False: добавить health_token (get_or_create)
# - иначе: health_token=None
```

`get_or_create_health_token()` вызывается один раз если хотя бы один из источников `inline_token` не подключён — без лишних DB-запросов.

---

## Frontend: изменения в `settings.js` и `settings.css`

### `_renderSourceRow(s)` — добавляет кнопку и панель

```js
function _renderSourceRow(s) {
  const statusClass = s.connected ? 'source-status connected' : 'source-status';
  const statusText  = s.connected
    ? `подключён · ${_fmtDate(s.last_updated)}`
    : 'не подключён';

  const connectBtn = s.connected
    ? ''
    : `<button class="connect-btn" onclick="toggleConnect('${s.id}')">Подключить ›</button>`;

  const panel = s.connected
    ? ''
    : `<div class="connect-panel" id="panel-${s.id}">${_renderConnectPanel(s)}</div>`;

  return `
    <div class="settings-row">
      <div class="row-icon">${s.icon}</div>
      <div class="row-label">
        ${s.name}
        <div class="row-sub ${statusClass}">${statusText}</div>
      </div>
      ${connectBtn}
    </div>
    ${panel}`;
}
```

### `_renderConnectPanel(s)` — HTML инструкции по типу flow

**`coming_soon`:**
```html
<div class="connect-content coming-soon">
  Поддержка подключения появится в следующем обновлении.
</div>
```

**`inline_token` — Apple Health** (с выбором метода):
```html
<div class="connect-content">
  <p>Выбери способ подключения:</p>
  <button onclick="selectAppleMethod('hae', '${token}')">💰 Health Auto Export</button>
  <button onclick="selectAppleMethod('shortcut', '${token}')">🆓 iOS Shortcuts</button>
  <div id="apple-method-detail"></div>
</div>
```

После выбора `selectAppleMethod(method, token)` заменяет `#apple-method-detail` инструкцией по образцу `hae_setup_text()` / `shortcut_setup_text()` из `apple_health_connect.py`.

**`inline_token` — Health Connect** (Android):
```html
<div class="connect-content">
  <p>Только для Android. Используй тот же ключ что и Apple Health.</p>
  <ol>
    <li>Установи APK: <a href="..." target="_blank">health-connect-webhook v1.9.10</a></li>
    <li>URL: <code>https://botkin.health/android_health_v1</code></li>
    <li>Token: <code>${token}</code> <button onclick="copyToken('${token}')">Скопировать</button></li>
  </ol>
</div>
```

**`tg_deeplink` — CGM:**
```html
<div class="connect-content">
  <ol>
    <li>Открой FreeStyle Libre 3 → ☰ → Connected Apps → LibreLinkUp</li>
    <li>Нажми Invite Follower и введи: <code>dr@botkin.health</code></li>
  </ol>
  <a class="connect-tg-btn" href="tg://resolve?domain=Botkin_md_bot&start=connect_cgm">
    Запустить ожидание в боте →
  </a>
</div>
```

### `toggleConnect(id)` — аккордеон

```js
function toggleConnect(id) {
  // Закрыть все остальные открытые панели
  document.querySelectorAll('.connect-panel.open').forEach(p => {
    if (p.id !== `panel-${id}`) p.classList.remove('open');
  });
  // Переключить текущую
  document.getElementById(`panel-${id}`).classList.toggle('open');
}
```

### CSS (дополнение к `settings.css`)

```css
.connect-btn {
  font-size: 13px;
  color: var(--tg-theme-link-color);
  background: none;
  border: none;
  padding: 0 4px;
  cursor: pointer;
  white-space: nowrap;
}

.connect-panel {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.25s ease;
  background: var(--tg-theme-secondary-bg-color);
  border-radius: 0 0 10px 10px;
  padding: 0 12px;
}

.connect-panel.open {
  max-height: 600px;
  padding: 10px 12px;
}

.connect-content { font-size: 13px; line-height: 1.5; }
.connect-content code { font-size: 12px; background: rgba(0,0,0,0.06); padding: 1px 4px; border-radius: 3px; }
.connect-content ol { padding-left: 16px; margin: 6px 0; }
.connect-tg-btn {
  display: inline-block;
  margin-top: 8px;
  padding: 6px 12px;
  background: var(--tg-theme-button-color);
  color: var(--tg-theme-button-text-color);
  border-radius: 8px;
  text-decoration: none;
  font-size: 13px;
}
.coming-soon { color: var(--tg-theme-hint-color); font-style: italic; }
```

---

## Тесты

Новые тесты в `tests/test_data_sources_api.py`:

| Тест | Что проверяет |
|------|---------------|
| `test_connect_info_schema` | Каждый источник возвращает `connect_info` с полем `flow` одного из допустимых значений |
| `test_apple_health_returns_token_when_disconnected` | `health_token` присутствует и не null когда `connected=False` |
| `test_apple_health_no_token_when_connected` | `health_token` равен `null` когда `connected=True` |
| `test_garmin_zepp_netatmo_flow_coming_soon` | Три источника возвращают `flow="coming_soon"` |
| `test_cgm_flow_tg_deeplink` | CGM возвращает `flow="tg_deeplink"` и `deeplink` содержит `connect_cgm` |
| `test_health_connect_returns_token_when_disconnected` | Health Connect получает `health_token` когда не подключён |

---

## Граничные случаи

| Случай | Поведение |
|--------|-----------|
| Новый пользователь (нет токена в БД) | `get_or_create_health_token()` создаёт на лету — ок |
| Источник подключился пока пользователь читал инструкцию | При следующем `loadDataSources()` кнопка исчезнет — достаточно |
| Два аккордеона одновременно | `toggleConnect` закрывает предыдущий при открытии нового |
| Health Connect — пользователь на iPhone | Показывается с пометкой «только для Android» в тексте инструкции |
| Неизвестный `flow` в будущем | Фронтенд рендерит `coming_soon` как fallback |

---

## Файлы, которые меняются

| Файл | Изменение |
|------|-----------|
| `telegram-bot/webhook/profile_api.py` | `get_data_sources()` — добавить `connect_info` и `health_token` в ответ |
| `telegram-bot/webapp/settings.js` | `_renderSourceRow`, `_renderConnectPanel`, `toggleConnect`, `selectAppleMethod`, `copyToken` |
| `telegram-bot/webapp/settings.css` | Стили `.connect-btn`, `.connect-panel`, `.connect-panel.open`, `.connect-tg-btn`, `.coming-soon` |
| `telegram-bot/webapp/index.html` | Без изменений (структура уже есть) |
| `tests/test_data_sources_api.py` | 6 новых тестов |
