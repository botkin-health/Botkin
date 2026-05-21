# Аудит зависимостей — 21.05.2026

Снимок outdated-пакетов в контейнере `healthvault_bot` на момент ночной сессии.
Этот документ — список рекомендаций для ручного апгрейда при следующей пересборке
Docker-образа (`./deploy.sh --force-rebuild`).

## ✅ Применено в этой сессии

| Пакет | Было | Стало | Причина |
|---|---|---|---|
| `pyjwt` | `==2.8.0` (strict pin) | `>=2.8.0` | Минорные апдейты 2.9-2.12 безопасны, strict pin был наследием NanoClaw |

После следующего `--force-rebuild` pip установит PyJWT 2.12.1 (или новее).

## 🟢 Безопасный апгрейд при следующем rebuild — patch/minor

Все используют `>=` или не пинятся вообще, так что rebuild подхватит автоматически.
Перечислены чтобы знать что обновится:

| Пакет | Текущая | Latest | Изменение |
|---|---|---|---|
| `aiohappyeyeballs` | 2.6.1 | 2.6.2 | patch |
| `certifi` | 2026.4.22 | 2026.5.20 | дата (CA roots) |
| `click` | 8.3.3 | 8.4.0 | minor |
| `greenlet` | 3.5.0 | 3.5.1 | patch |
| `jiter` | 0.14.0 | 0.15.0 | minor |
| `numpy` | 2.4.5 | 2.4.6 | patch |
| `types-PyYAML`, `types-requests` | даты | даты | type stubs |
| `watchfiles` | 1.1.1 | 1.2.0 | minor |
| `yarl` | 1.23.0 | 1.24.2 | minor |

## 🟡 Major bumps — нужна ручная проверка

Перед апгрейдом — почитать changelog, прогнать тесты, проверить что не сломалось.

### `garminconnect` 0.2.38 → 0.3.2 (pinned strict)
**Где используется:** `scripts/import/download_garmin_data.py`, `scripts/garmin/*.py` — daily sync.
**Риск:** Сменился API methods между minor — могут переименоваться вызовы.
**Зависимость:** `garth` (см. ниже), тоже надо бампать.
**Recommendation:** при следующем апгрейде создать ветку, бампнуть оба, тестировать `python3 scripts/import/download_garmin_data.py` локально, потом deploy.

### `garth` 0.5.21 → 0.8.0
**Где используется:** OAuth для Garmin (auth-токены).
**Риск:** Любые изменения в OAuth-flow могут привести к 401/403 на следующий sync.
**Recommendation:** бампать вместе с garminconnect.

### `google-ai-generativelanguage` 0.6.15 → 0.11.0 (Gemini)
**Где используется:** `core/llm/router.py` — fallback LLM (если OpenAI и Anthropic упали).
**Риск:** Не критично — это резервный путь. Можно безопасно бампать.
**Recommendation:** apply on next rebuild, monitor fallback path.

### `protobuf` 5.29.6 → 7.35.0
**Где используется:** Зависимость google-ai-* (через grpcio).
**Риск:** Большой скачок (2 major). Может ломать совместимость.
**Recommendation:** не бампать в одиночку — пусть google-ai потянет нужную версию через свои deps.

### `dbus-fast` 4.2.5 → 5.0.3
**Где используется:** Зависимость `bleak` (Bluetooth). Используется для Mi-весов через BLE-scanning (`scripts/import/*scale*`).
**Риск:** Major bump может изменить Bluetooth-API.
**Recommendation:** не критично — Mi-веса сейчас идут через Apple Health (HAE), не BLE напрямую. Можно бампать.

### `ast_serialize` 0.4.0 → 0.5.0
**Где используется:** Тестовая утилита, минорный пакет.
**Recommendation:** safe to bump.

### `pip`, `setuptools`, `wheel` (мета-инструменты)
Обновятся автоматически в `--force-rebuild` если Dockerfile это делает.

## 💻 Mac dev environment

Локальный venv в `./venv/` сломан — shebang ссылается на `HealthVault-engine/venv/bin/python3.13`, которого нет (Botkin переименовался). Тесты локально не запускаются.

**Recommendation:** пересоздать venv:
```bash
cd "<project_dir>"
rm -rf venv
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt
```

Это даст актуальные версии на Mac. Запуск тестов будет работать локально без необходимости лезть в контейнер.

## Что НЕ делал автономно

- ❌ Не пересобирал Docker-образ — `--force-rebuild` это 5-10 мин с pip-install, риск сломать прод во сне
- ❌ Не запускал `pip install --upgrade` внутри контейнера — изменения теряются на следующем rebuild, ложное чувство «обновлено»
- ❌ Не пересоздавал Mac venv — требует подтверждения что всё чисто (могут быть локальные не-закоммиченные правки)

## Когда удобно применить

1. Проснёшься → ревью этого документа
2. Решишь — какие из 🟡 пунктов готов бампнуть
3. Запустить `./deploy.sh --force-rebuild` — подхватит все `>=` обновления + ручные правки в requirements.txt
4. Smoke test бота: «привет», простой вопрос про данные, фото еды
5. Pересоздать Mac venv (1-2 минуты)
