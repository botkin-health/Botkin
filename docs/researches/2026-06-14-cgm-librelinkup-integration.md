# CGM (глюкоза) через LibreLinkUp — интеграция и troubleshooting

**Дата:** 2026-06-14 (интеграция), дополнено 2026-06-17 (Cloudflare/476)
**Статус:** в проде (Alex, Nika); архитектурное решение — [ADR-0005](../architecture/decisions/0005-cgm-librelinkup-integration.md)

> Зачем док: код CGM будут править сторонние разработчики. Здесь — как это устроено, какие грабли уже найдены, и на чём основаны решения (опыт автоматизаторов + реверс-инжиниринг API).

## Архитектура (коротко)

```
Сенсор Libre 3 → приложение FreeStyle Libre 3 (телефон) → облако Abbott (libreview.io)
   └─ пользователь приглашает follower dr@botkin.health (LibreLinkUp)
Сервер Botkin: pylibrelinkup(dr@botkin.health, EU) → get_patients() → graph()/latest()
   → upsert в glucose_readings (mmol/L), маппинг patient_id→telegram_id в cgm_connections
```

- **Клиент:** [`pylibrelinkup`](https://github.com/robberwick/pylibrelinkup), регион `APIUrl.EU` (Нидерланды/EU аккаунт). Пин `<0.11`.
- **Код:** `scripts/import/librelinkup.py` (импорт + `get_cached_client`/`refresh_glucose_for_telegram`), общий рантайм `core/health/glucose_runtime.py`, онбординг `telegram-bot/handlers/connect_cgm.py`, эндпоинты `recent_glucose`/`glucose_stats` в `agent_tools_api.py`.
- **Время:** хранить `factory_timestamp` (UTC, tz-aware), НЕ `timestamp` (наивное локальное) — иначе сдвиг в `timestamptz` (#129).
- **Токен:** JWT кэшируется на диск `data/cache/llu_token.json` (0o600) и переиспользуется (#135).

## Known issues / troubleshooting

### 1. HTTP 476 на `authenticate()` — Cloudflare WAF temp-ban (главная грабля)
**Симптом:** `476 Client Error … /llu/auth/login`; данные по уже выданному токену при этом качаются.
**Причина:** `api-*.libreview.io` за Cloudflare WAF временно банит **по IP** клиентов, похожих на ботов. Триггеры: (а) всплеск логинов, (б) отсутствие `User-Agent`. Док сообщества: nightscout-librelink-up [#146](https://github.com/timoschlueter/nightscout-librelink-up/issues/146) («banned you temporarily»), [#182](https://github.com/timoschlueter/nightscout-librelink-up/issues/182).
**Длительность:** Cloudflare rate-limit — от 10 сек до 24 ч (зависит от настройки владельца; free/pro cap 1 ч). Конкретная настройка Abbott публично не задокументирована. **Надёжный сигнал — заголовок `Retry-After`** (его стоит логировать, см. #141).
**Фикс:** (1) слать `User-Agent` как рабочие клиенты (#139); (2) переиспользовать токен, не логиниться часто (#135); (3) backoff при 476 — не штурмовать (#141). Активный бан UA/прокси не снимают — должен истечь сам; в это время **не дёргать логин**.
**Anti-pattern:** датацентровый прокси/VPN (Hetzner/собственный VPN) для обхода — Cloudflare жёстче метит датацентровые IP, может не помочь/ухудшить.

### 2. `connect_cgm`/`recent_glucose` сами себя банят
**Симптом:** 476 не проходит часами, повторные вопросы про глюкозу не помогают.
**Причина:** on-demand refresh и `/connect_cgm` логинятся на **каждый** запрос → бьют по забаненному IP → продлевают бан.
**Фикс:** backoff (#141) + переиспользование токена (#135). Пока не реализован backoff — при 476 на несколько часов не спрашивать бота про глюкозу и не жать `/connect_cgm`.

### 3. Region redirect (eu / eu2 / de / …)
**Симптом:** логин не на том региональном эндпоинте.
**Причина:** аккаунт привязан к региону; при логине не на том регионе API отвечает `status:0, data:{redirect:true, region:"xx"}` — надо повторить на `api-xx.libreview.io`. `pylibrelinkup` обрабатывает основные регионы; мы используем `APIUrl.EU`.

### 4. Terms of Use / «error 4»
**Симптом:** логин отбивается после обновления ToU.
**Причина:** Abbott обновил условия — нужно перелогиниться в **приложении** LibreLinkUp и принять новые ToU ([GlucoDataHandler #172](https://github.com/pachi81/GlucoDataHandler/issues/172)). (В нашем кейсе 17.06 это НЕ помогло → причина была в Cloudflare-бане, не в ToU.)

### 5. Инвайт follower не появляется
**Симптом:** приглашённый аккаунт не видит пациента, окна Accept нет.
**Причина/фикс:** окно Accept всплывает при **открытии/свежем входе** приложения LibreLinkUp; если нет — проверить интернет/уведомления и **переотправить инвайт на точный email** ([Abbott FAQ](https://www.librelinkup.com/faqs)). `get_patients()` возвращает только **принятые** связи.

### 6. Таймзона глюкозы +Nч
**Симптом:** время точек сдвинуто на смещение TZ (у МСК +3ч).
**Причина/фикс:** хранили `timestamp` (наивное локальное) в `timestamptz`. Использовать `factory_timestamp` (UTC). Исправлено в #129; существующие строки чистятся `TRUNCATE` + ре-импорт.

## Ссылки
- Клиент: [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup)
- API reverse-engineering: [khskekec gist](https://gist.github.com/khskekec/6c13ba01b10d3018d816706a32ae8ab2), [libreview-unofficial](https://github.com/FokkeZB/libreview-unofficial)
- Рабочий клиент с UA: [nightscout-librelink-up](https://github.com/timoschlueter/nightscout-librelink-up)
