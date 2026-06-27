# CGM (глюкоза) через LibreLinkUp — интеграция и troubleshooting

**Дата:** 2026-06-14 (интеграция), дополнено 2026-06-17 (Cloudflare/476 deep-dive)
**Статус:** в проде (Alex, Nika); архитектурное решение — [ADR-0005](../architecture/decisions/0005-cgm-librelinkup-integration.md)

> Зачем этот doc: код CGM будут править сторонние разработчики. Здесь — как устроена интеграция, какие грабли уже найдены, и на чём основаны решения (опыт автоматизаторов + реверс-инжиниринг API).

## Архитектура (коротко)

```
Сенсор Libre 3 → приложение FreeStyle Libre 3 (телефон) → облако Abbott (libreview.io)
   └─ пользователь приглашает follower dr@botkin.health (LibreLinkUp)
Сервер Botkin: pylibrelinkup(dr@botkin.health, EU) → get_patients() → graph()/latest()
   → upsert в glucose_readings (mmol/L), маппинг patient_id→telegram_id в cgm_connections
```

- **Клиент:** [`pylibrelinkup`](https://github.com/robberwick/pylibrelinkup), регион `APIUrl.EU` (EU аккаунт). Пин `<0.11`.
- **Код:** `scripts/import/librelinkup.py` (импорт + `get_cached_client`/`refresh_glucose_for_telegram`), общий рантайм `core/health/glucose_runtime.py`, онбординг `telegram-bot/handlers/connect_cgm.py`, эндпоинты `recent_glucose`/`glucose_stats` в `agent_tools_api.py`.
- **Время:** хранить `factory_timestamp` (UTC, tz-aware), НЕ `timestamp` (наивное локальное) — иначе сдвиг в `timestamptz` ([#129](https://github.com/botkin-health/Botkin/issues/129)).
- **Токен:** JWT кэшируется на диск `data/cache/llu_token.json` (0o600) и переиспользуется ([#135](https://github.com/botkin-health/Botkin/issues/135)).

---

## Known issues / troubleshooting

### 1. HTTP 476 на `authenticate()` — Cloudflare WAF IP-бан (главная грабля)

**Симптом:** `476 Client Error: <none> for url: https://api-eu.libreview.io/llu/auth/login`.
Данные по уже выданному JWT-токену при этом продолжают качаться — бан только на эндпоинт логина.

**Природа ошибки:** 476 — **нестандартный HTTP-код, специфичный для Cloudflare WAF**. Это не ответ Abbott API; это ответ Cloudflare-прокси, которая стоит перед `api-*.libreview.io`. В Python requests он появляется как обычный `HTTPError`. `pylibrelinkup` обрабатывает только HTTP 429 (`LLUAPIRateLimitError`); 476 нужно ловить отдельно на уровне приложения.

**Подтверждённые триггеры (из опыта сообщества):**

1. **Отсутствие `User-Agent`** — главная причина. `pylibrelinkup` по умолчанию не шлёт `User-Agent`, только `product: llu.android` и `version: ...`. Cloudflare WAF идентифицирует такой запрос как бот и банит. Рабочие клиенты (nightscout-librelink-up, нативные приложения) шлют полный UA мобильного браузера и не страдают.
   - Источник: [nightscout PR #130](https://github.com/timoschlueter/nightscout-librelink-up/pull/130) и [PR #131](https://github.com/timoschlueter/nightscout-librelink-up/pull/131) «Added Cloudflare DDOS protection bypass»; наш [#139](https://github.com/botkin-health/Botkin/issues/139).

2. **Датацентровые IP (Hetzner, AWS, Heroku, OVH)** — Cloudflare агрессивнее метит ASN облачных провайдеров. Зафиксировано: когда один клиент Hetzner-датацентра создаёт аномальную нагрузку, Cloudflare может забанить **весь IP-диапазон** этого провайдера.
   - Цитата из [nightscout #182](https://github.com/timoschlueter/nightscout-librelink-up/issues/182): *"Sometimes the linkup portal starts to block certain IP address ranges. My servers run in Hetzner locations... My only solution so far is to run multiple docker instances in multiple locations and then switch between them once they are being blocked."*
   - Из [nightscout #160](https://github.com/timoschlueter/nightscout-librelink-up/issues/160): пользователь пробовал несколько Hetzner-локаций (Германия, Хельсинки) — обе заблокированы. Единственное, что сработало — домашний residential IP.

3. **Слишком частый поллинг логина** — интервал <5 минут между вызовами `/llu/auth/login`. Из [nightscout #182](https://github.com/timoschlueter/nightscout-librelink-up/issues/182): пользователь с `LINK_UP_TIME_INTERVAL=3` (3 мин) получил бан; переход на 5 мин снял проблему.

4. **TLS-fingerprinting** — Cloudflare может детектировать Python `requests` / Node.js 18+ по TLS cipher suite и блокировать.
   - Цитата из [nightscout #128](https://github.com/timoschlueter/nightscout-librelink-up/issues/128) (maintainer timoschlueter): *"Cloudflare seems to detect that we are connecting from a Node 18+ client and denies access... To fight this, I am now generating a custom cypher-list for the axios client so that the script looks unique from Cloudflare's point of view."*
   - Для Python — кастомный `HTTPAdapter` с нестандартным `ssl.SSLContext` (см. [httptoolkit.com/blog/tls-fingerprinting-node-js](https://httptoolkit.com/blog/tls-fingerprinting-node-js/)).
   - В Botkin **пока не реализовано** — кандидат на следующий фикс если 476 вернётся после снятия текущего бана.

**Длительность бана:**

Официально Abbott не документирует. Единственный зафиксированный data point из реального `Retry-After` заголовка 476-ответа ([gist khskekec, комментарий июнь 2025](https://gist.github.com/khskekec/6c13ba01b10d3018d816706a32ae8ab2?permalink_comment_id=5330276)):

```
"retry-after": "65620"   # секунд → ~18.2 часа
```

Повторные логин-попытки во время активного бана **продлевают** его — Cloudflare видит попытки обойти ограничение. При 476 — ждать, не штурмовать.

**Отличие от account-level lockout (HTTP 429, code 60):**

Отдельный механизм — Abbott API rate-limit, не Cloudflare:
```json
{"status":429,"data":{"code":60,"data":{"failures":3,"interval":60,"lockout":300},"message":"locked"}}
```
`lockout: 300` = 5 минут при 3 неудачных попытках подряд. `pylibrelinkup` обрабатывает как `LLUAPIRateLimitError`. Может возникать параллельно с 476. Источник: [nightscout #218](https://github.com/timoschlueter/nightscout-librelink-up/issues/218), [nightscout #146](https://github.com/timoschlueter/nightscout-librelink-up/issues/146).

**Что сделано в Botkin:**

| Фикс | PR/Issue | Статус |
|------|----------|--------|
| `User-Agent: Mozilla/5.0 (iPhone; CPU OS 17_4_1...)` инъекция в `pylibrelinkup.HEADERS` | [#139](https://github.com/botkin-health/Botkin/issues/139) | ✅ в проде |
| Персист JWT в `data/cache/llu_token.json` (0o600) — логин редкое событие | [#135](https://github.com/botkin-health/Botkin/issues/135) | ✅ в проде |
| Exponential backoff 15м→30м→60м→120м при 476; `LoginOnCooldownError` | [#141](https://github.com/botkin-health/Botkin/issues/141) | ✅ в проде |
| Кастомный TLS cipher (Python `HTTPAdapter`) — спуфинг TLS fingerprint | — | ❌ не реализовано, запас на будущее |

**Anti-patterns:**
- ❌ **Датацентровый VPN/прокси** для обхода активного бана — Cloudflare жёстче метит датацентровые ASN, риск ухудшить ситуацию. Residential IP работает, datacenter — нет.
- ❌ Повторные вызовы `authenticate()` при активном 476 — продлевают бан. Читать `Retry-After` и ждать.
- ❌ Поллинг логина чаще раза в 5 минут.

---

### 2. `connect_cgm`/`recent_glucose` сами себя банят

**Симптом:** 476 не проходит часами, повторные вопросы про глюкозу не помогают.
**Причина:** on-demand refresh и `/connect_cgm` логинятся на **каждый** запрос → бьют по забаненному IP → продлевают бан.
**Фикс:** backoff ([#141](https://github.com/botkin-health/Botkin/issues/141)) + переиспользование токена ([#135](https://github.com/botkin-health/Botkin/issues/135)). При активном 476 не спрашивать бота про глюкозу и не жать `/connect_cgm` — ждать истечения `Retry-After`.

---

### 3. Region redirect (eu / eu2 / de / …)

**Симптом:** логин не на том региональном эндпоинте.
**Причина:** аккаунт привязан к региону; при логине не на том регионе API отвечает `status:0, data:{redirect:true, region:"xx"}` — надо повторить на `api-xx.libreview.io`. `pylibrelinkup` обрабатывает основные регионы; мы используем `APIUrl.EU`.

---

### 4. Terms of Use / «error 4»

**Симптом:** логин отбивается после обновления ToU.
**Причина:** Abbott обновил условия — нужно перелогиниться в **приложении** LibreLinkUp и принять новые ToU ([GlucoDataHandler #172](https://github.com/pachi81/GlucoDataHandler/issues/172)). (В нашем кейсе 17.06 это НЕ помогло → причина была в Cloudflare-бане, не в ToU.)

---

### 5. Инвайт follower не появляется

**Симптом:** приглашённый аккаунт не видит пациента, окна Accept нет.
**Причина/фикс:** окно Accept всплывает при **открытии/свежем входе** приложения LibreLinkUp; если нет — проверить интернет/уведомления и **переотправить инвайт на точный email** ([Abbott FAQ](https://www.librelinkup.com/faqs)). `get_patients()` возвращает только **принятые** связи.

---

### 6. Таймзона глюкозы +Nч

**Симптом:** время точек сдвинуто на смещение TZ (у МСК +3ч).
**Причина/фикс:** хранили `timestamp` (наивное локальное) в `timestamptz`. Использовать `factory_timestamp` (UTC). Исправлено в [#129](https://github.com/botkin-health/Botkin/issues/129); существующие строки чистятся `TRUNCATE` + ре-импорт.

---

## Ссылки

**Клиент и API:**
- [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup) — Python-клиент, используем в Botkin
- [khskekec gist — HTTP dump FreeStyle Libre 3](https://gist.github.com/khskekec/6c13ba01b10d3018d816706a32ae8ab2) — реверс-инжиниринг запросов; здесь зафиксирован реальный `Retry-After: 65620` при 476
- [InventivetalentDev/LibreViewApi](https://github.com/InventivetalentDev/LibreViewApi/blob/master/LibreLinkUpApi.md) — документация эндпоинтов
- [DiaKEM/libre-link-up-api-client](https://github.com/DiaKEM/libre-link-up-api-client) — TypeScript клиент
- [libreview-unofficial](https://github.com/FokkeZB/libreview-unofficial)

**Cloudflare 476 — issue-треды (читать при отладке):**
- [nightscout-librelink-up #128](https://github.com/timoschlueter/nightscout-librelink-up/issues/128) — самый детальный разбор: TLS fingerprinting + UA-фикс (от maintainer'а)
- [nightscout-librelink-up #130](https://github.com/timoschlueter/nightscout-librelink-up/pull/130) / [#131](https://github.com/timoschlueter/nightscout-librelink-up/pull/131) — PR с Cloudflare bypass
- [nightscout-librelink-up #146](https://github.com/timoschlueter/nightscout-librelink-up/issues/146) — account-level temp ban
- [nightscout-librelink-up #160](https://github.com/timoschlueter/nightscout-librelink-up/issues/160) — датацентровые IP (Hetzner) vs residential
- [nightscout-librelink-up #182](https://github.com/timoschlueter/nightscout-librelink-up/issues/182) — Cloudflare rate-limit на Heroku, поллинг 3мин→бан, 5мин→ок
- [nightscout-librelink-up #218](https://github.com/timoschlueter/nightscout-librelink-up/issues/218) — persistent 429 locked overnight

**Botkin issues:**
- [#129](https://github.com/botkin-health/Botkin/issues/129) — таймзона UTC fix
- [#135](https://github.com/botkin-health/Botkin/issues/135) — персист JWT
- [#139](https://github.com/botkin-health/Botkin/issues/139) — User-Agent fix
- [#141](https://github.com/botkin-health/Botkin/issues/141) — exponential backoff
