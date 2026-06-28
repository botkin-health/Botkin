# Переезд mini-app на botkin.health (снятие времянки orangegate)

> Issue [#212](https://github.com/botkin-health/Botkin/issues/212). Финальный шаг роадмапа
> «переезд legacy-домена `health.orangegate.cc` → `botkin.health`».
> Требует SSH к проду (зона владельца сервера) — кодовая часть (целевой vhost) уже в репо:
> [`nginx-botkin.health.conf`](nginx-botkin.health.conf).

## Зачем

После релиза 27.06 на проде стоит **времянка** `BOTKIN_PUBLIC_URL=https://health.orangegate.cc`
в `/opt/botkin/.env`. После #209 кнопка «Дневник» и все публичные ссылки (`/share`, `/report`)
строятся из `public_base_url()` (= `BOTKIN_PUBLIC_URL`). Если просто поставить `botkin.health`,
не тронув nginx — кнопка ведёт на `botkin.health/webapp/` → **404**, потому что vhost
`botkin.health` отдаёт `/webapp/` и `/api/` как **статику лендинга** (`/opt/botkin-site/`),
а не проксирует на бот.

Цель: бренд-домен `botkin.health` отдаёт весь mini-app и публичные ссылки с бота → времянку
`BOTKIN_PUBLIC_URL=orangegate` можно снять (дефолт `public_base_url()` уже `https://botkin.health`,
см. `config/settings.py`).

## Что должно проксироваться на бот (`127.0.0.1:8081`)

Полный перечень путей, которые дёргает mini-app и публичные ссылки бота:

| Путь | Источник | Назначение |
|---|---|---|
| `/webapp/`, `/webapp/index.html`, `/webapp/*` | `apple_health.py` (StaticFiles) | статика mini-app (api.js, dashboard.js, settings.js, day.*, settings.css) |
| `/api/day`, `/api/meal/item`, `/api/meal`, `/api/favorites` | `nutrition_api.py` | дневник еды |
| `/api/supplements/day`, `/api/supplements/take` | `supplements_api.py` | добавки |
| `/api/profile/bmr`, `/api/profile/timezone`, `/api/profile/data_sources`, `/api/dashboard_url` | `profile_api.py` | профиль, источники данных (#150), ссылка на дашборд |
| `/api/settings` | `apple_health.py` | настройки mini-app |
| `/api/agent/*` | `agent_tools_api.py` | agent-тулзы (под `/api/`) |
| `/mc/{token}` | `dashboard.py` | дашборд (`/share`, iframe вкладки «Здоровье») |
| `/r/{token}` | `report.py` | HTML-отчёты (`/report`, #204) |

> Одной локации `^~ /api/` достаточно для всех `/api/*` (включая `/api/agent`, `/api/profile`,
> `/api/settings`). У лендинга своих `/api/` нет — конфликта не будет.

## 🔴 Грабля nginx (обязательно учесть)

В текущем vhost есть `location ~* \.(css|js|jpg|...)$` (кэш статики лендинга). Эта **регекс-локация
перебивает префиксный** `location /webapp/` для `*.js`/`*.css` → `api.js`, `settings.js`,
`dashboard.js` отдадутся из `/opt/botkin-site/` (404 / чужой файл), mini-app не загрузится.

**Решение:** backend-локации обязаны быть с модификатором **`^~`** (`location ^~ /webapp/`,
`^~ /api/` и т.д.) — он отключает проверку регекс-локаций при совпадении префикса. В готовом
[`nginx-botkin.health.conf`](nginx-botkin.health.conf) это уже сделано.

## Шаги применения (SSH к проду)

1. **Подложить backend-локации в vhost `botkin.health`.** Взять блоки `location ^~ …` из
   [`nginx-botkin.health.conf`](nginx-botkin.health.conf) (на сервере они могут жить в
   `snippets/botkin-backend.conf`, подключаемом через `include` в vhost). **Не трогать
   `location /`** (статика лендинга).
2. **Проверить и перезагрузить nginx:**
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
3. **Проверить mini-app/ссылки на botkin.health (ДО снятия времянки):**
   ```bash
   curl -so /dev/null -w '%{http_code}\n' https://botkin.health/webapp/          # ожидаем 200
   curl -sI https://botkin.health/webapp/api.js | grep -i content-type           # application/javascript, не text/html
   curl -so /dev/null -w '%{http_code}\n' https://botkin.health/r/<любой_token>  # 200 (не 404 от лендинга)
   ```
   `/api/*` отдаёт 401/403 без Telegram initData — это нормально (значит дошло до бота, а не до статики).
4. **Снять времянку** в `/opt/botkin/.env`: убрать строку `BOTKIN_PUBLIC_URL=https://health.orangegate.cc`
   (дефолт = `https://botkin.health`) **или** выставить её в `https://botkin.health`.
5. **Перезапустить бота:**
   ```bash
   cd /opt/botkin && docker compose -f docker-compose.prod.yml up -d
   ```
6. **Перепроверить:** открыть бота → кнопка «Дневник» ведёт на `botkin.health/webapp/`; команды
   `/share` и `/report` отдают ссылки на `botkin.health/mc/…` и `botkin.health/r/…` (200, не orangegate).
7. **(опц.) Обратная совместимость:** в vhost `health.orangegate.cc` добавить
   `location /webapp { return 301 https://botkin.health$request_uri; }` (и `/r/`, `/mc/`) — чтобы
   старые ссылки не били в 404. HAE-webhook (`/apple_health_v2`) на orangegate **не трогать** —
   он продолжает работать там.

## Откат

Вернуть `BOTKIN_PUBLIC_URL=https://health.orangegate.cc` в `/opt/botkin/.env` + `up -d` —
кнопка/ссылки снова на orangegate (там `location /` проксирует всё на `:8081`). Локации `^~`
в vhost `botkin.health` откату не мешают (лишними не будут).
