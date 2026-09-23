# Хранение токенов и секретов

> Перенесено из корневого `CLAUDE.md` 23.09.2026 дословно: раздел справочный и нужен не в каждой задаче,
> а CLAUDE.md целиком загружается в каждую сессию Claude Code. Источник истины по этой теме — этот файл.


| Что | Где | Примечание |
|---|---|---|
| API-ключи (OpenAI, Gemini, Telegram) | `.env` / `.env.production` | Постоянные, не истекают |
| Пароли (Garmin, Zepp, Netatmo) | `.env` | Для OAuth-потоков |
| OAuth-токены (Zepp, и др.) | `data/cache/tokens.json` | Истекают через 5-7 дней, требуют `--reauth` |
| Netatmo refresh_token | `.env` (`NETATMO_REFRESH_TOKEN`) | Долгоживущий |

`data/cache/` в `.gitignore` — токены не попадают в git.

### sshpass и PATH

`sshpass` установлен в `/opt/homebrew/bin/sshpass`. В subshell-скриптах (bash, Python subprocess) `/opt/homebrew/bin` может отсутствовать в PATH, поэтому **всегда использовать полный путь** во всех скриптах. Все `.sh` и `.py` в `scripts/` уже исправлены. Если добавляешь новый скрипт с `sshpass` — сразу пиши полный путь.

### Zepp reauth — правильный порядок

1. Запустить `scripts/import/zepp_api.py --reauth` → скрипт выведет URL для логина
2. Открыть URL в браузере, залогиниться в Xiaomi
3. Скопировать redirect URL вида `hm.xiaomi.com/watch.do?code=...`
4. Запустить `scripts/import/zepp_api.py --code КОД` (только сам код после `?code=`)
5. Дождаться `✅ Токен получен!` — токен сохранён в `data/cache/tokens.json`
6. **Если после этого упала ошибка** (sshpass, сеть и т.п.) — **не передавать `--code` повторно!**
   OAuth-код одноразовый. Просто запустить `scripts/import/zepp_api.py` без флагов — токен уже в кэше.
