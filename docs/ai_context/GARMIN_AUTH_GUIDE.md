# Garmin Auth — Полное руководство

> Последнее обновление: 2026-04-02. Этот файл — источник истины по всем вопросам
> авторизации Garmin: мак, сервер, бот, мобильное приложение.

---

## Архитектура (как работает сейчас)

```
[Garmin Cloud]
      │
      │  OAuth2 (garth-токены, ~28 дней)
      ▼
[Mac] download_garmin_data.py
      │ скачивает JSON → data/garmin/daily-summary/
      │ токены хранит → data/cache/garth_tokens/
      │
      ├─► push_garmin_to_db.sh
      │     ├── пушит JSON → activity_log на сервере (SSH psql)
      │     └── копирует токены → /opt/healthvault/data/garth/895655/ на сервере
      │
[Hetzner Server]
      │
      ├─► PostgreSQL: activity_log (исторические данные + сегодня)
      │
      └─► Telegram Bot
            └── /day → sync_today_garmin()
                  ├── проверяет кеш (15 мин в synced_at)
                  ├── garth.resume(garth_dir) → Garmin API (1 запрос)
                  └── upsert в activity_log
```

**Ключевой принцип:** сервер никогда не логинится паролем. Только токены.
Все логины паролем — только с мака, в фоне, при `/sync`.

---

## Важно: версии библиотек (не менять!)

| Место | garminconnect | Формат токенов |
|---|---|---|
| Мак (venv) | **0.2.38** | `oauth1_token.json` + `oauth2_token.json` |
| Сервер (Docker) | **0.2.38** (pinned в requirements.txt) | тот же |

**Не обновлять garminconnect до 0.3.x!** Версия 0.3.0 использует другой формат токенов (`garmin_tokens.json`), несовместимый с тем что генерирует garth 0.2.38. Если обновить только сервер или только мак — токены перестанут читаться и нужно будет повторный логин паролем.

---

## Garth-токены: что это и где лежат

Garth — библиотека OAuth2-авторизации для Garmin Connect. После одного логина
паролем сохраняет два файла, которые позволяют авторизоваться без пароля ~28 дней:

| Файл | Что содержит | Срок жизни |
|---|---|---|
| `oauth1_token.json` | Consumer key/secret | Бессрочно |
| `oauth2_token.json` | access_token + refresh_token | access: ~1 день, refresh: ~28 дней |

Garth автоматически обновляет `access_token` через `refresh_token` при первом
использовании после истечения. Пароль при этом не нужен.

### Где хранятся токены

| Место | Путь | Используется |
|---|---|---|
| Мак (рабочие токены) | `data/cache/garth_tokens/` | `download_garmin_data.py` |
| Сервер (для бота) | `/opt/healthvault/data/garth/895655/` | `sync_today_garmin()` в боте |
| Внутри контейнера | `/app/data/garth/895655/` | Тот же путь, примонтирован через volume |

---

## Что происходит при `/day` в боте

1. Вызывается `core.health.garmin_data.sync_today_garmin(user_id, today)`
2. Проверяется `activity_log.synced_at` для сегодня — если < 15 мин назад, возвращает кеш
3. Загружаются garth-токены из `/app/data/garth/895655/`
4. `garth.resume()` → если access_token протух, автоматически обновляется через refresh_token
5. Один запрос `client.get_stats(today)` к Garmin API
6. Результат сохраняется в `activity_log`, возвращается `(active_calories, 'ok')`

**Если что-то пошло не так:**
- Нет файлов токенов → `status='error'`, показывает `⚠️ Garmin недоступен`
- refresh_token протух (> 28 дней без `/sync`) → то же
- Garmin API вернул 429 → то же

---

## Как обновить токены (плановое, раз в ~25 дней)

Просто запустить `/sync` на маке. `push_garmin_to_db.sh` автоматически:
1. Скачивает свежие данные через `download_garmin_data.py` — garth обновляет токены
2. Пушит данные в БД
3. Копирует свежие токены на сервер

---

## Диагностика проблем

### Симптом: `/day` показывает `⚠️ Garmin недоступен`

**Шаг 1** — проверить логи бота:
```bash
ssh root@116.203.213.137 'docker logs --tail 50 healthvault_bot 2>&1' | grep -i garmin
```

**Возможные ошибки и решения:**

| Ошибка в логах | Причина | Решение |
|---|---|---|
| `no garth tokens at /app/data/garth/895655` | Токены не скопированы на сервер | Запустить `/sync` на маке |
| `garth.resume() failed` | Токены протухли (> 28 дней) | Запустить `/sync` на маке |
| `429 Rate Limit` | Слишком частые логины паролем | Никогда не должно случаться — бот не логинится паролем. Если появилось — значит в коде ещё есть password fallback |
| `HTTP 403` | IP сервера забанен Garmin | Подождать 24-48 часов, потом запустить `/sync` с мака для обновления токенов |

**Шаг 2** — проверить токены на сервере:
```bash
ssh root@116.203.213.137 'ls -la /opt/healthvault/data/garth/895655/'
```
Должны быть `oauth1_token.json` и `oauth2_token.json`.

**Шаг 3** — проверить срок жизни refresh_token на маке:
```bash
python3 -c "
import json, time
d = json.load(open('data/cache/garth_tokens/oauth2_token.json'))
exp = d.get('refresh_token_expires_at', 0)
print(f'refresh_token истекает через {(exp-time.time())/86400:.1f} дней')
"
```

**Шаг 4** — если refresh_token протух, нужен полный re-login:
```bash
cd HealthVault
source venv/bin/activate
python3 scripts/garmin/download_garmin_data.py --reauth
```
(или запустить `download_garmin_data.py` — он попросит ввести пароль, сохранит новые токены)

**Шаг 5** — скопировать токены вручную на сервер:
```bash
sshpass -p 'PASS' scp \
  data/cache/garth_tokens/oauth1_token.json \
  data/cache/garth_tokens/oauth2_token.json \
  root@116.203.213.137:/opt/healthvault/data/garth/895655/
```

---

### Симптом: `/day` показывает 0 ккал (без ⚠️)

Данных в `activity_log` нет за сегодня, и Garmin API тоже ничего не вернул
(например, рано утром до первой активности). Это нормально.

---

### Симптом: 429 Rate Limit в логах

Кто-то вызывает Garmin API с паролем слишком часто.

Проверить нет ли старого кода `sync_missing_garmin_days` или password fallback:
```bash
ssh root@116.203.213.137 'docker exec healthvault_bot grep -rn "sync_missing_garmin\|password.*login\|Garmin(email" /app/'
```
Если нашлось — убрать password login из кода бота и задеплоить.

После 429 Garmin снимает бан через ~24-48 часов самостоятельно.

---

### Симптом: мак не может скачать данные Garmin

Проверить токены на маке:
```bash
python3 -c "
import json, time
d = json.load(open('data/cache/garth_tokens/oauth2_token.json'))
exp = d.get('refresh_token_expires_at', 0)
print('refresh ok:', exp > time.time(), f'({(exp-time.time())/86400:.0f}d left)')
"
```

Если протухли — запустить `download_garmin_data.py` с любым флагом, он попросит пароль.

---

## История инцидентов

### Март 2026: первый 429

**Что случилось:** `sync_missing_garmin_days` вызывался при каждом `/day`.
При 5 пропущенных днях = 5 логинов паролем за секунды → Garmin заблокировал сервер.

**Как лечили:** получили garth-токены вручную через CAS SSO, записали в AI_CHANGELOG.
Но garth-код в `sync_garmin_data` так и не появился (остался password login).

### Апрель 2026: второй 429

**Что случилось:** при починке `/day` добавили `sync_today_garmin`, который снова
делал password fallback → сервер снова получил 429.

**Как лечили:**
1. Убрали password fallback полностью из бота
2. Скопировали garth-токены с мака на сервер
3. Добавили автокопирование токенов в `push_garmin_to_db.sh`
4. Теперь бот использует только garth-токены, пароль на сервере никогда не используется

---

## Регулярное обслуживание

| Когда | Действие |
|---|---|
| Раз в ~25 дней | `/sync` на маке (автоматически обновляет токены) |
| При `⚠️ Garmin недоступен` | Проверить логи, запустить `/sync` |
| При переезде сервера | Скопировать `data/garth/` вместе с остальными данными |
| При смене пароля Garmin | Запустить `download_garmin_data.py --reauth` на маке, потом `/sync` |
