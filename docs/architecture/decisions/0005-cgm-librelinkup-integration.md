# 0005. Интеграция CGM (глюкоза) через LibreLinkUp

**Status:** Accepted
**Date:** 2026-06-17
**Deciders:** Александр Лысковский
**Context:** Нужно тянуть данные непрерывного мониторинга глюкозы (Abbott FreeStyle Libre 3 / 3 Plus) для пользователей Боткина и давать их AI-врачу (корреляция «еда ↔ сахар»). У Abbott нет официального API; единственный программный путь — неофициальный **LibreLinkUp** (follower-приложение для «наблюдателей»).

## Решение

Тянем глюкозу через **follower-аккаунт LibreLinkUp** `dr@botkin.health` (Python-клиент [`pylibrelinkup`](https://github.com/robberwick/pylibrelinkup), регион EU). Пользователь приглашает этот аккаунт как follower из приложения FreeStyle Libre 3 → сервер логинится под ним, видит всех приглашённых через `get_patients()` и пишет точки в `glucose_readings` (mmol/L). Пользователь свои креды Боткину **не отдаёт**.

Маппинг `patient_id (UUID Abbott) → telegram_id` — в таблице `cgm_connections`. Онбординг — `/connect_cgm` (авто-детект нового пациента). Свежесть «в момент вопроса» — on-demand pull в `recent_glucose`.

Три решения, продиктованные реальностью неофициального API за Cloudflare (см. «Последствия» и troubleshooting-док):
1. **Персист JWT на диск** (`data/cache/llu_token.json`) и переиспользование — логин редкое событие (#135).
2. **User-Agent в каждом запросе** (как у рабочих клиентов) — иначе Cloudflare WAF метит как бота и банит (#139).
3. **Backoff на логин** при 476 — не штурмовать забаненный IP, не банить самих себя (#141).

## Альтернативы

- **Официальный API Abbott** — не существует для сторонних разработчиков. Отвергнуто (нет варианта).
- **Nightscout как промежуточный слой** — лишний сервис и БД ради того, что `pylibrelinkup` даёт напрямую. Отвергнуто (оверинжиниринг для нашего масштаба).
- **Чтение с телефона/Bluetooth (xDrip-стиль)** — требует приложения на каждом устройстве и не серверное. Отвергнуто (не вписывается в серверную архитектуру).
- **Хранить локальное `timestamp` измерения** — наивное локальное время → сдвиг в `timestamptz`. Отвергнуто в пользу `factory_timestamp` (UTC). См. #129.

## Последствия

**Позитивные**
- Multi-user из коробки: один follower-аккаунт видит всех через `get_patients()`.
- Пользователь не делится кредами; отзыв доступа — на его стороне (убрать follower).
- Данные durable в Postgres + RLS-изоляция по пользователю.

**Негативные / trade-offs**
- API **неофициальный**: может меняться/ломаться (версия `pylibrelinkup` пиннится `<0.11`, апгрейд — только с ревью диффа, т.к. клиент шлёт креды на эндпоинт Abbott).
- За `api-*.libreview.io` стоит **Cloudflare WAF** → частые/«ботоподобные» логины → временный IP-бан (HTTP **476**). Отсюда персист токена + User-Agent + backoff.
- История подтягивается не задним числом — Abbott отдаёт ~последние 12 часов; глубокая ретроспектива копится только вперёд.

**Что НЕ делать (anti-pattern)**
- ❌ Логиниться на каждый запрос (on-demand/cron без переиспользования токена) — Cloudflare забанит. Только `get_cached_client` (токен с диска).
- ❌ Слать запросы без `User-Agent`.
- ❌ Штурмовать логин при 476 (продлевает бан) — нужен backoff с уважением `Retry-After`.
- ❌ Писать `timestamp` (локальное) в `glucose_readings.ts` — только `factory_timestamp` (UTC).
- ❌ Гонять глюкозу через датацентровый прокси/VPN, ожидая обойти бан — Cloudflare жёстче метит датацентровые IP.

## Ссылки

- Research + troubleshooting: [docs/researches/2026-06-14-cgm-librelinkup-integration.md](../../researches/2026-06-14-cgm-librelinkup-integration.md)
- PR/issue: #96 (интеграция), #129 (таймзона + on-demand + /sync), #135 (персист токена), #139 (User-Agent), #141 (backoff)
- Опыт сообщества: nightscout-librelink-up [#146](https://github.com/timoschlueter/nightscout-librelink-up/issues/146), [#182](https://github.com/timoschlueter/nightscout-librelink-up/issues/182); [reverse-engineering API dump](https://gist.github.com/khskekec/6c13ba01b10d3018d816706a32ae8ab2)
- Клиент: [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup)
