# Подключение семейного юзера к BotkinClaw

Runbook для будущих onboarding'ов через `scripts/onboard_family_user.py`.

## Когда применять

- Юзер уже подключён к боту (есть строка в `users` с telegram_id).
- В `~/.../FamilyHealth/<name>/` лежит распарсенный `knowledge_base.json`.
- Хочется, чтобы юзер мог общаться с агентом не только про еду.

Если KB ещё не распарсен — сначала прогнать `scripts/import/parse_lab_pdfs.py`.

## Архитектура (что куда едет)

```
FamilyHealth/<name>/knowledge_base.json  →  scp  →  /opt/healthvault/data/kb/kb_<tid>.json
FamilyHealth/<name>/PROFILE.md            ↘
                                            generate_persona  →  agent_system_prompt
core/packs.py                             ↗
                                                 ↓
                                          users(telegram_id=<tid>)
                                          + cohort/pack_name/agent_system_prompt
```

Артефакт промпта коммитится в `scripts/server/agent_prompts/<short_name>.md` для git-ревью и ручных правок.

## Pre-flight

1. **Проверить что юзер есть в БД:**
   ```bash
   /opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
       "docker exec healthvault_postgres psql -U healthvault -d healthvault \
        -c \"SELECT telegram_id, first_name, cohort FROM users WHERE telegram_id=<TID>;\""
   ```
2. **Проверить KB:**
   ```bash
   python3.13 -c "import json; kb=json.load(open('FamilyHealth/.../knowledge_base.json'));
   print(list(kb.keys()), 'blood_tests:', len(kb.get('blood_tests',[])))"
   ```
3. **Доступные packs** — см. `core/packs.py`. Сейчас:
   - `generic` — без специфического фокуса
   - `bariatric` — снижение веса + метаболика
   - `cardiac` — кардиометаболический риск
   - `respiratory_allergic` — астма + аллерго-история + регулярный скрининг

## Окружение

Перед запуском CLI экспортируй env:

```bash
cd /Users/alexlyskovsky/.../Botkin
set -a; source .env; set +a
export SERVER_PASSWORD="..."  # см. scripts/fetch_remote_nutrition.sh
```

Необходимые переменные:
- `ANTHROPIC_API_KEY` — для LLM-генерации промпта
- `TELEGRAM_BOT_TOKEN` — для welcome'а (только если `--send-welcome`)
- `SERVER_PASSWORD` — Hetzner root

## Шаг 1. Dry-run

Собрать команду и прогнать с `--dry-run`:

```bash
python3.13 scripts/onboard_family_user.py --enroll \
    --tid <TID> \
    --family-folder "/Users/.../FamilyHealth/<Name> — Здоровье" \
    --name "<ShortName>" \
    --full-name "<Полное Имя Отчество>" \
    --age "<X лет>" \
    --birth-date "YYYY-MM-DD" \
    --location "<Город>" \
    --cohort family \
    --cohort-relationship "<родственная связь>" \
    --bio-line "<одна строка контекста>" \
    --pack <pack> \
    --style <ty|vy> \
    --dry-run
```

Проверить:
- KB summary совпадает с ожиданием (количество blood_tests, размер).
- Pack корректный.
- Current state на сервере как ожидалось (external/generic для нового юзера).
- Превью промпта (первые 500 симв) читается, не выглядит машинным мусором.
- Никакой выдумки про лечащих врачей, операции, которых не было.

## Шаг 2. Реальный enroll

Тот же команд без `--dry-run`. Сначала **без** `--send-welcome` — чтобы проверить E2E перед уведомлением:

```bash
python3.13 scripts/onboard_family_user.py --enroll ... --yes
```

После успешного enroll скрипт коммитит артефакт промпта локально.

## Шаг 3. E2E verify

Прежде чем отправлять welcome — проверить что агент реально видит данные:

```python
python3.13 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(<TID>, 'какой у меня был последний витамин D?'))
"
```

Ожидаем ответ с реальным значением и датой из KB.

## Шаг 4. Welcome

Если E2E ок — отправить welcome:

```bash
python3.13 -c "
from scripts.onboard import welcome_sender
text = welcome_sender.build_welcome_text(name='<Name>', style='ty', inviter_name='Александр')
msg_id = welcome_sender.send_welcome(chat_id=<TID>, text=text)
print(f'Sent message_id={msg_id}')
"
```

Или используя CLI (если в будущем добавим `--send-welcome-only`).

## Откат / частичное обновление

| Что нужно | Команда |
|---|---|
| Перезалить KB после обновления локального | `--refresh-kb --tid X --family-folder ...` |
| Пересоздать промпт через Claude | `--refresh-prompt --tid X --family-folder ... --name ... --pack ...` |
| Применить ручную правку промпта | `--refresh-prompt --tid X --from-file scripts/server/agent_prompts/<name>.md` |
| Полностью отозвать enrollment | `--unenroll --tid X` |

## Troubleshooting

- **Anthropic 529 на 4.6** — скрипт сам делает quick retry (0.7s) и fallback на 4.5. Если оба упали — повторить через 1-2 минуты или использовать `--from-file` со старым артефактом промпта.
- **scp прерван** — `--enroll` сам откатит KB-файл при ошибке DB UPDATE. Если scp упал — ничего не было применено, можно перезапустить.
- **Process killed между scp и mv** — может остаться `kb_<tid>.json.tmp` в `/opt/healthvault/data/kb/`. Удалить вручную: `ssh root@host "rm -f /opt/healthvault/data/kb/kb_<tid>.json.tmp"`.
- **psql: 0 rows updated → UserNotFoundError** — юзер не существует в `users`. Проверь telegram_id.
- **Welcome не дошёл** — `chat_id` должен совпадать с telegram_id юзера, юзер должен был хотя бы раз написать боту (chat существует).
- **`--enroll requires: ...`** — argparse объявил эти поля optional, но `cmd_enroll` валидирует на старте. Проверь команду на missing-args.
- **Артефакт промпта попал в commit с другими unstaged изменениями** — нет, `_git_commit_artifact` стейджит только сам файл промпта.

## Документы

- Дизайн: [docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md](../superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md)
- План имплементации: [docs/superpowers/plans/2026-05-22-igor-botkin-onboarding.md](../superpowers/plans/2026-05-22-igor-botkin-onboarding.md)
- Pack registry: [core/packs.py](../../core/packs.py)
- Шаблон промпта: [scripts/server/agent_prompts/templates/family_active_coach.md](../../scripts/server/agent_prompts/templates/family_active_coach.md)
- CLI: [scripts/onboard_family_user.py](../../scripts/onboard_family_user.py)
