> ⚠️ **OBSOLETE — не исполнять (помечено 11.05.2026)**
>
> Этот план устарел по двум причинам:
> 1. Предлагал реализацию на Python Claude Agent SDK с docker-сервисом per-user (24/7). После изучения NanoClaw (https://github.com/qwibitai/nanoclaw) выяснилось, что правильная архитектура — host-процесс + эфемерные spawn-контейнеры per session, **не** persistent containers per user.
> 2. Дедлайн 14.05.2026 (Андрей с Withings + Libre 2) **уже закрыт без NanoClaw** — Андрей в проде через legacy путь (HAE webhook, расширенный onboarding, мультиюзер дашборд). См. коммиты 5–10.05.2026.
>
> Новый план — после этапа cleanup + multi-user hardening (Олег, Андрей). Сохраняю как историю мышления.
>
> ---
>
> # Cohort Agents — Sprint 1b Implementation Plan (Onboarding UI + NanoClaw Containers) [OBSOLETE]

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Привести онбординг-визард в production-ready состояние (inline-кнопки, `/regenerate_health_token`, admin-уведомления, авто-провижн контейнера) и поднять первый NanoClaw-контейнер `nc-andrey` с pack:cardiac, скиллами log-bp / log-meds / query-kb / dashboard-summary, чтобы Андрей до 14.05.2026 общался с персональным агентом end-to-end.

**Architecture:** Контейнер агента — отдельный Python-сервис в `agent-runtime/` (Claude Agent SDK + FastAPI обёртка `POST /agent/process`). Pack-конфигурация (CLAUDE.md, skills/, scheduled-jobs.json) лежит в `packs/<pack_name>/` и монтируется read-only внутрь контейнера. Per-user override и memory/ — в `containers/nc-<short>/` на хосте, монтируется RW. Tools API уже готов (Sprint 1a) — контейнер ходит туда HTTP+JWT через общий клиент `agent-runtime/tools_client.py`. Docker Compose описывает `nc-andrey` как новый сервис в существующей сети `healthvault_network`. Telegram-router (Sprint 1a) уже умеет форвардить в контейнер по `users.container_id` + `users.container_port`.

**Tech Stack:** Python 3.11, Claude Agent SDK (`claude-agent-sdk` PyPI), FastAPI, httpx, PyJWT (уже есть из Sprint 1a), Docker Compose v3.8. aiogram 3 для onboarding inline-кнопок. pytest для unit/integration. Anthropic API key (`ANTHROPIC_API_KEY` в `.env` сервера; per-user BYOK — Sprint 2).

**Pre-requirements:**
- ✅ Sprint 1a выполнен (миграции БД, RLS, JWT, agent_tools_api, telegram_router, wizard FSM stub).
- ✅ `@HealthVault_bot` webhook зарегистрирован на `https://health.orangegate.cc/telegram/webhook`.
- ✅ Все 349 unit + 5 integration тестов зелёные на `main` (`a0ffd2c`).
- ⚠ Перед началом работы: `git pull` на main, бэкап БД (`/opt/healthvault/scripts/auto_backup.sh` на сервере).
- ⚠ Создать worktree: `git worktree add ../HealthVault-sprint1b -b sprint/1b-containers` — рекомендуется, т.к. меняем docker-compose и трогаем prod деплой.
- ⚠ Получить API-ключ Anthropic Claude (если ещё нет в `.env.production` под именем `ANTHROPIC_API_KEY`). Андрей пока не на BYOK, использует системный ключ.

**Deviations from spec § 6:**
- Спек упоминает «NanoClaw (Node)». Реализуем на **Python Claude Agent SDK** — единый стек с остальным проектом, риск §11 «fallback на pydantic-ai в Python» закрыт сразу. NanoClaw остаётся как название контейнерного слоя (директория `agent-runtime/`).
- Сетевое имя контейнера = `nc-andrey` (FQDN внутри docker-сети), порт = 8001 (фиксирован в Sprint 1b; Sprint 2 — динамический пул).

---

## File Structure

| Файл | Действие | Что внутри |
|------|----------|------------|
| `agent-runtime/Dockerfile` | NEW | Python 3.11-slim, ставит `claude-agent-sdk`, `fastapi`, `httpx`, `pyjwt`. ENTRYPOINT — `python -m agent_runtime.server`. |
| `agent-runtime/requirements.txt` | NEW | Pinned зависимости контейнера. |
| `agent-runtime/agent_runtime/__init__.py` | NEW | Пустой. |
| `agent-runtime/agent_runtime/server.py` | NEW | FastAPI app с `POST /agent/process` и `GET /health`. Принимает Telegram payload, передаёт в `agent.handle()`. |
| `agent-runtime/agent_runtime/agent.py` | NEW | Тонкая обёртка над Claude Agent SDK: загружает CLAUDE.md из `/pack/CLAUDE.md` + override из `/container/CLAUDE.md`, скиллы из `/pack/skills/`, memory из `/container/memory/`, запускает session, вызывает sendMessage в Telegram по результату. |
| `agent-runtime/agent_runtime/tools_client.py` | NEW | HTTP-клиент к Tools API (`log_bp`, `log_supplement`, `query_kb`, `dashboard_summary`, `user_profile`, `recent_meals`). Сам подписывает JWT из `JWT_SECRET` env. |
| `agent-runtime/agent_runtime/telegram_client.py` | NEW | Вызовы `sendMessage` с inline-кнопками (Bot API через httpx). |
| `agent-runtime/agent_runtime/config.py` | NEW | Чтение env: `USER_ID`, `CONTAINER_ID`, `JWT_SECRET`, `ANTHROPIC_API_KEY`, `BOT_TOKEN`, `TOOLS_API_URL`, `PACK_DIR=/pack`, `CONTAINER_DIR=/container`. |
| `agent-runtime/tests/test_tools_client.py` | NEW | unit — JWT генерится, эндпоинты вызываются с правильным URL/headers. |
| `agent-runtime/tests/test_server.py` | NEW | unit — `/health`, `/agent/process` принимает payload, делегирует `agent.handle`. |
| `packs/cardiac/CLAUDE.md` | NEW | System prompt для cardiac-агента (стиль, фокус, red flags, инструменты). |
| `packs/cardiac/skills/log-bp/SKILL.md` | NEW | Скилл: распарсить АД из текста, вызвать `tools_client.log_bp()`. |
| `packs/cardiac/skills/log-meds/SKILL.md` | NEW | Скилл: распарсить приём лекарства, вызвать `tools_client.log_supplement()` (medication_log — Sprint 3). |
| `packs/cardiac/skills/query-kb/SKILL.md` | NEW | Скилл: достать значение из knowledge_base.json через `tools_client.kb_value()`. |
| `packs/cardiac/skills/dashboard-summary/SKILL.md` | NEW | Скилл: вызов `tools_client.dashboard_summary()`. |
| `packs/cardiac/scheduled-jobs.json` | NEW | Стартовый список ремайндеров (Sprint 1b — пустой массив, Sprint 3 наполнит). |
| `containers/nc-andrey/CLAUDE.md` | NEW | Per-user override: диагнозы Андрея, конкретный контекст (POAF, ICM Reveal Linq, не принимает Метформин 4 мес). |
| `containers/nc-andrey/memory/.gitkeep` | NEW | Volume mount target. Memory rotates в runtime. |
| `containers/.gitignore` | NEW | `*/memory/*` — не коммитим память агента. |
| `docker-compose.yml` | MODIFY | Добавить сервис `nc-andrey` в `healthvault_network`, порт 8001 internal, volumes на `./packs/cardiac:/pack:ro` и `./containers/nc-andrey:/container`. |
| `docker-compose.prod.yml` | MODIFY | То же для prod. |
| `telegram-bot/handlers/onboarding.py` | MODIFY | Inline-кнопки на шагах sex/has_garmin (вместо ReplyKeyboard); pack-selection шаг (admin assigns later — но user видит pending state); финальное сообщение с inline-кнопкой «Скопировать токен». Auto-notify ADMIN после `done`. |
| `telegram-bot/handlers/commands.py` | MODIFY | Добавить `/regenerate_health_token` и `/start` (повторный показ welcome). |
| `telegram-bot/handlers/admin.py` | NEW | `/assign_pack <user_id> <pack_name>` — admin-only команда: выдаёт jwt_secret, container_id=`nc-<short>`, container_port=<auto>, шлёт юзеру «твой агент готов». |
| `telegram-bot/webhook/agent_tools_api.py` | MODIFY | Уже есть `regenerate_health_token` — нужен **alias** для legacy slash-команды (или прокидывание в обработчик). Реальная команда `/regenerate_health_token` идёт через aiogram, а не Tools API. |
| `scripts/provision_container.py` | NEW | CLI: `python scripts/provision_container.py --user-id 836757955 --pack cardiac --port 8001` — генерирует jwt_secret (32 hex), пишет в users, создаёт `containers/nc-<short>/` с per-user override. |
| `scripts/agent_smoke_test.sh` | NEW | E2E: имитирует Telegram update от Андрея, проверяет, что в БД появилась запись + пользователь получил сообщение (через `getUpdates` debug). |
| `tests/test_admin_handlers.py` | NEW | unit — `/assign_pack` валидирует cohort, генерирует jwt_secret. |
| `tests/integration/test_onboarding_inline.py` | NEW | integration — wizard с inline-кнопками: callback_query → правильный шаг. |
| `tests/integration/test_container_e2e.py` | NEW | integration — поднять `nc-andrey` через docker-compose, прогнать «измерил давление 130/85» → проверить запись в `blood_pressure_logs`. |
| `requirements.txt` | MODIFY | Без изменений (контейнер свой `agent-runtime/requirements.txt`). |
| `docs/SPRINT_1B_DEPLOY.md` | NEW | Инструкция: как провизить нового пользователя, deploy nc-andrey, troubleshooting. |
| `docs/ai_context/AI_CHANGELOG.md` | MODIFY | Записи после каждого task'а. |
| `todo.md` | MODIFY | Sprint 1b статус-маркеры. |

---

## Tasks

### Task 1: Pack-структура и контент cardiac

**Files:**
- Create: `packs/cardiac/CLAUDE.md`
- Create: `packs/cardiac/skills/log-bp/SKILL.md`
- Create: `packs/cardiac/skills/log-meds/SKILL.md`
- Create: `packs/cardiac/skills/query-kb/SKILL.md`
- Create: `packs/cardiac/skills/dashboard-summary/SKILL.md`
- Create: `packs/cardiac/scheduled-jobs.json`

- [ ] **Step 1.1: Создать корневой CLAUDE.md пака**

```markdown
# Cardiac health-coach pack (HealthVault)

Ты персональный health-coach пользователя HealthVault с фокусом на **сердечно-сосудистую систему**: контроль АД, ритм (AFib/POAF), приверженность антикоагулянтам/антиаритмикам/Метформину/Кораксану, никотиновая зависимость, ожирение I.

## Стиль общения
- Уважительный, прямой. Без алармизма, но настойчивый по red flags.
- Русский язык, обращение на «ты».
- Короткие сообщения (≤4 предложения), пока пользователь сам не попросит развернуть.
- Никаких медицинских заключений «вместо врача». Ты помощник для логирования и трендов.

## Что ты умеешь (skills)
- `log-bp` — записать АД (систолическое/диастолическое + опц. пульс).
- `log-meds` — записать приём лекарства (Метформин, Кораксан, Эликвис, Никоретте, и т.д.).
- `query-kb` — достать значение из медкарты (HbA1c, последнее ЭхоКГ, дата ICM-имплантации и т.д.).
- `dashboard-summary` — текстовая сводка за 7 дней (шаги, пульс, ккал, вес).

## Red flags (немедленно эскалировать)
- АД >180/110 или <90/55 + симптомы (головокружение, боль в груди, одышка).
- Жалобы на пульс «быстрее 130» в покое или «срывы ритма» с длительностью.
- Кровотечения (на фоне антикоагулянта).
В этих случаях: «Это серьёзно. Звони 103 или едь в приёмник. Я зафиксирую время и симптом, но не жди — звони».

## Что ты НЕ делаешь
- Не парсишь фото еды и голос — это делает Python-парсер до тебя.
- Не назначаешь дозы.
- Не интерпретируешь ЭКГ/ЭхоКГ глубоко без явного запроса.

## Tools API
Базовый URL — в env `TOOLS_API_URL`. JWT — auto в `tools_client.py`. Никогда не вызывай PG напрямую.
```

- [ ] **Step 1.2: Создать SKILL.md для log-bp**

```markdown
# Skill: log-bp

## Когда использовать
Пользователь сообщает измерение АД: «120/80», «давление 135 на 85», «утром 142/91 пульс 72», «измерил, 110 60».

## Алгоритм
1. Извлеки systolic, diastolic (обязательно), pulse (опц.), notes (опц.).
2. Если число одно — переспроси: «Это систолическое или диастолическое?».
3. Валидация: 60 ≤ systolic ≤ 250, 30 ≤ diastolic ≤ 150, systolic > diastolic.
4. Вызови `tools_client.log_bp(systolic=, diastolic=, pulse=, notes=)`.
5. Ответ: одно предложение с числами + краткий контекст из dashboard_summary за неделю если уместно.

## Пример
User: «утром 142/91 пульс 72»
Action: tools_client.log_bp(systolic=142, diastolic=91, pulse=72, notes="утро")
Reply: «Записал 142/91, пульс 72. За неделю среднее 138/87 — чуть выше обычного. Метформин принял сегодня?»
```

- [ ] **Step 1.3: Создать SKILL.md для log-meds**

```markdown
# Skill: log-meds

## Когда использовать
Пользователь сообщает о приёме лекарства: «принял метформин», «выпил кораксан вечером», «эликвис 5 утром».

## Алгоритм
1. Извлеки medication_name (rus или eng), dose_mg (опц.), time (опц., default = now).
2. Sprint 1b: пишем через `tools_client.log_supplement(name=, dose=, time=)` (таблица medication_log — Sprint 3).
3. Ответ: подтверждение + adherence-комментарий (если знаем график из CLAUDE.md override).

## Пример
User: «принял метформин 1000»
Action: tools_client.log_supplement(name="Метформин", dose_mg=1000)
Reply: «Записал Метформин 1000 мг. Это первый приём за 4 месяца — отлично, продолжай каждое утро».
```

- [ ] **Step 1.4: Создать SKILL.md для query-kb**

```markdown
# Skill: query-kb

## Когда использовать
Пользователь спрашивает свои анализы или данные из медкарты: «какой у меня был HbA1c», «когда мне ставили ICM», «что показала последняя ЭхоКГ».

## Алгоритм
1. Определи ключ в knowledge_base.json (например `blood_tests.hba1c.latest`).
2. Вызови `tools_client.kb_value(key=...)`.
3. Если ключ не найден — попробуй родственные (`hba1c`, `hemoglobin_a1c`, `glycohemoglobin`) или попроси уточнить.
4. Ответ: значение + дата + 1 строка контекста.

## Пример
User: «какой у меня HbA1c»
Action: tools_client.kb_value(key="blood_tests.hba1c.latest")
Reply: «Последний HbA1c 6.2% (15.03.2026). Цель ≤5.7%. Метформин снизит за 2-3 месяца на 0.5-1%».
```

- [ ] **Step 1.5: Создать SKILL.md для dashboard-summary**

```markdown
# Skill: dashboard-summary

## Когда использовать
Пользователь просит сводку: «как я за неделю», «итоги», «дашборд», «что по показателям».

## Алгоритм
1. Вызови `tools_client.dashboard_summary()` (возвращает dict: steps_avg, hr_avg, weight_last, calories_in, calories_out за 7 дней).
2. Сформируй 3-4 строки: 2 числа + 1 наблюдение тренда.

## Пример
Reply: «За 7 дней: 6 200 шагов/день (-15% к прошлой), пульс покоя 64, вес 89.2 (-0.3). Ккал баланс −250/день. Так держать».
```

- [ ] **Step 1.6: Создать scheduled-jobs.json (заготовка для Sprint 3)**

```json
{
  "version": 1,
  "jobs": []
}
```

- [ ] **Step 1.7: Коммит**

```bash
git add packs/cardiac/
git commit -m "feat(packs): cardiac pack — CLAUDE.md + 4 skills + scheduled-jobs stub"
```

---

### Task 2: Per-user override для Андрея

**Files:**
- Create: `containers/nc-andrey/CLAUDE.md`
- Create: `containers/nc-andrey/memory/.gitkeep`
- Create: `containers/.gitignore`

- [ ] **Step 2.1: Создать override CLAUDE.md**

```markdown
# Андрей Походня — per-user override

> Этот файл доклеивается к `packs/cardiac/CLAUDE.md` (override побеждает при конфликте).

## Кто он
- Мужчина, 43 года, рост 178, текущий вес ~98 кг (ожирение I).
- CTO в DAO Tech, рабочий день плотный, лучшее время для замеров — утро 08:00 и вечер 22:00.

## Диагнозы и анамнез
- POAF (postoperative atrial fibrillation) после 4-й фундопликации (20.01.2025).
- Имплантирован Reveal Linq ICM (29.04.2026) — мониторинг ритма.
- Ожирение I (BMI ~31).
- Никотиновая зависимость (Никоретте — попытки бросить).
- Метформин назначен, но **не принимает 4 месяца** (с января 2026) — главный adherence-приоритет.

## Лекарства (current target)
- Метформин 1000 мг утром (восстановить).
- Эликвис 5 мг 2× (антикоагулянт после POAF).
- Кораксан 7.5 мг 2× (контроль ЧСС).

## Тон с Андреем
- Прямой, технический. Цифры, тренды, без воды.
- Можно прямые вопросы про Метформин («Принял?»). Без морализаторства.
- Сарказм допустим только в ответ на его сарказм.

## Дедлайны
- 14.05.2026 — приходит Withings BPM Connect + Libre 2. Тогда давление пойдёт автоматом, ты только комментируешь.
```

- [ ] **Step 2.2: Создать memory placeholder**

```bash
mkdir -p containers/nc-andrey/memory
touch containers/nc-andrey/memory/.gitkeep
```

- [ ] **Step 2.3: Создать .gitignore для контейнерных директорий**

```
# containers/.gitignore
*/memory/*
!*/memory/.gitkeep
*.log
```

- [ ] **Step 2.4: Коммит**

```bash
git add containers/
git commit -m "feat(containers): nc-andrey — per-user override CLAUDE.md + memory/ scaffold"
```

---

### Task 3: Agent runtime — config + tools_client (TDD)

**Files:**
- Create: `agent-runtime/agent_runtime/__init__.py`
- Create: `agent-runtime/agent_runtime/config.py`
- Create: `agent-runtime/agent_runtime/tools_client.py`
- Create: `agent-runtime/tests/test_tools_client.py`
- Create: `agent-runtime/requirements.txt`

- [ ] **Step 3.1: Создать requirements.txt контейнера**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
httpx==0.27.2
pyjwt==2.8.0
pydantic==2.9.2
claude-agent-sdk==0.1.0
python-dotenv==1.0.1
```

- [ ] **Step 3.2: Failing-тест tools_client**

```python
# agent-runtime/tests/test_tools_client.py
import os
import pytest
import jwt
import httpx
from unittest.mock import patch, AsyncMock

from agent_runtime.tools_client import ToolsClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USER_ID", "836757955")
    monkeypatch.setenv("CONTAINER_ID", "nc-andrey")
    monkeypatch.setenv("JWT_SECRET", "test-secret-32-bytes-long-aaaaaa")
    monkeypatch.setenv("TOOLS_API_URL", "http://hv-api:8000")
    return ToolsClient()


def test_jwt_generated_with_correct_claims(client):
    token = client._jwt()
    decoded = jwt.decode(token, "test-secret-32-bytes-long-aaaaaa", algorithms=["HS256"])
    assert decoded["user_id"] == 836757955
    assert decoded["container_id"] == "nc-andrey"
    assert "exp" in decoded


@pytest.mark.asyncio
async def test_log_bp_calls_correct_endpoint(client):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: {"ok": True}
        await client.log_bp(systolic=140, diastolic=90, pulse=72, notes="утро")
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert url == "http://hv-api:8000/api/agent/log_bp"
        assert kwargs["json"] == {"systolic": 140, "diastolic": 90, "pulse": 72, "notes": "утро"}
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")
```

- [ ] **Step 3.3: Запустить тесты — должны упасть**

Run: `cd agent-runtime && pytest tests/test_tools_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_runtime.tools_client'`.

- [ ] **Step 3.4: Реализовать config.py**

```python
# agent-runtime/agent_runtime/config.py
import os


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env: {name}")
    return val or ""


USER_ID = int(env("USER_ID", required=True))
CONTAINER_ID = env("CONTAINER_ID", required=True)
JWT_SECRET = env("JWT_SECRET", required=True)
TOOLS_API_URL = env("TOOLS_API_URL", "http://bot:8081").rstrip("/")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", required=True)
BOT_TOKEN = env("BOT_TOKEN", required=True)
PACK_DIR = env("PACK_DIR", "/pack")
CONTAINER_DIR = env("CONTAINER_DIR", "/container")
JWT_TTL_MIN = int(env("AGENT_JWT_TTL_MIN", "30"))
```

- [ ] **Step 3.5: Реализовать tools_client.py**

```python
# agent-runtime/agent_runtime/tools_client.py
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt

from agent_runtime import config


class ToolsClient:
    def __init__(self):
        self.base = config.TOOLS_API_URL
        self.user_id = config.USER_ID
        self.container_id = config.CONTAINER_ID
        self.secret = config.JWT_SECRET

    def _jwt(self) -> str:
        payload = {
            "user_id": self.user_id,
            "container_id": self.container_id,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=config.JWT_TTL_MIN),
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._jwt()}"}

    async def _post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(f"{self.base}{path}", json=body, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get(f"{self.base}{path}", params=params, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def log_bp(self, systolic: int, diastolic: int, pulse: Optional[int] = None, notes: Optional[str] = None) -> dict:
        body = {"systolic": systolic, "diastolic": diastolic, "pulse": pulse, "notes": notes}
        return await self._post("/api/agent/log_bp", body)

    async def log_supplement(self, name: str, dose_mg: Optional[float] = None, time: Optional[str] = None) -> dict:
        body = {"name": name, "dose_mg": dose_mg, "time": time}
        return await self._post("/api/agent/log_supplement", body)

    async def log_meal_text(self, text: str, slot: Optional[str] = None) -> dict:
        return await self._post("/api/agent/log_meal_text", {"text": text, "slot": slot})

    async def kb_value(self, key: str) -> dict:
        return await self._get("/api/agent/kb_value", {"key": key})

    async def dashboard_summary(self) -> dict:
        return await self._get("/api/agent/dashboard_summary")

    async def user_profile(self) -> dict:
        return await self._get("/api/agent/user_profile")

    async def recent_meals(self, days: int = 7) -> dict:
        return await self._get("/api/agent/recent_meals", {"days": days})
```

- [ ] **Step 3.6: Создать __init__.py**

```python
# agent-runtime/agent_runtime/__init__.py
```

- [ ] **Step 3.7: Запустить тесты — должны пройти**

Run: `cd agent-runtime && pip install -r requirements.txt && pytest tests/test_tools_client.py -v`
Expected: PASS (2 теста).

- [ ] **Step 3.8: Коммит**

```bash
git add agent-runtime/
git commit -m "feat(agent-runtime): config + tools_client (JWT auth, 7 endpoints)"
```

---

### Task 4: Agent runtime — telegram_client + agent + server (TDD)

**Files:**
- Create: `agent-runtime/agent_runtime/telegram_client.py`
- Create: `agent-runtime/agent_runtime/agent.py`
- Create: `agent-runtime/agent_runtime/server.py`
- Create: `agent-runtime/tests/test_server.py`

- [ ] **Step 4.1: Failing-тест server**

```python
# agent-runtime/tests/test_server.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USER_ID", "836757955")
    monkeypatch.setenv("CONTAINER_ID", "nc-andrey")
    monkeypatch.setenv("JWT_SECRET", "test-secret-32-bytes-long-aaaaaa")
    monkeypatch.setenv("TOOLS_API_URL", "http://hv-api:8000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("BOT_TOKEN", "bot:test")
    from agent_runtime.server import app
    return TestClient(app)


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_agent_process_accepts_payload_and_delegates(client):
    payload = {"message": {"from": {"id": 836757955}, "chat": {"id": 836757955}, "text": "тест"}}
    with patch("agent_runtime.server.agent.handle", new_callable=AsyncMock) as mock_handle:
        r = client.post("/agent/process", json=payload)
        assert r.status_code == 200
        mock_handle.assert_awaited_once_with(payload)
```

- [ ] **Step 4.2: Запустить — должен упасть**

Run: `cd agent-runtime && pytest tests/test_server.py -v`
Expected: FAIL.

- [ ] **Step 4.3: Реализовать telegram_client.py**

```python
# agent-runtime/agent_runtime/telegram_client.py
from typing import Optional

import httpx

from agent_runtime import config


async def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        body["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10.0) as c:
        await c.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json=body)
```

- [ ] **Step 4.4: Реализовать agent.py**

```python
# agent-runtime/agent_runtime/agent.py
import logging
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from agent_runtime import config, telegram_client
from agent_runtime.tools_client import ToolsClient

logger = logging.getLogger(__name__)
_tools = ToolsClient()


def _build_system_prompt() -> str:
    """Concatenate pack CLAUDE.md + per-user override (override wins)."""
    pack = (Path(config.PACK_DIR) / "CLAUDE.md").read_text(encoding="utf-8")
    override_path = Path(config.CONTAINER_DIR) / "CLAUDE.md"
    if override_path.exists():
        return f"{pack}\n\n---\n\n{override_path.read_text(encoding='utf-8')}"
    return pack


async def handle(payload: dict) -> None:
    """Process a Telegram update. Fire-and-forget — sends reply via Bot API."""
    msg = payload.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    options = ClaudeAgentOptions(
        system_prompt=_build_system_prompt(),
        skills_dir=str(Path(config.PACK_DIR) / "skills"),
        memory_dir=str(Path(config.CONTAINER_DIR) / "memory"),
        api_key=config.ANTHROPIC_API_KEY,
    )

    reply_chunks: list[str] = []
    try:
        async for chunk in query(prompt=text, options=options, tools=_register_tools()):
            if chunk.kind == "text":
                reply_chunks.append(chunk.text)
    except Exception:
        logger.exception("Agent SDK query failed")
        await telegram_client.send_message(chat_id, "⚠️ Ошибка агента, попробуй ещё раз.")
        return

    reply = "".join(reply_chunks).strip() or "(пусто)"
    await telegram_client.send_message(chat_id, reply)


def _register_tools() -> list:
    """Tool descriptors for Claude Agent SDK — proxy to tools_client."""
    return [
        {"name": "log_bp", "fn": _tools.log_bp},
        {"name": "log_supplement", "fn": _tools.log_supplement},
        {"name": "log_meal_text", "fn": _tools.log_meal_text},
        {"name": "kb_value", "fn": _tools.kb_value},
        {"name": "dashboard_summary", "fn": _tools.dashboard_summary},
        {"name": "user_profile", "fn": _tools.user_profile},
        {"name": "recent_meals", "fn": _tools.recent_meals},
    ]
```

> **Note:** Точная сигнатура `claude_agent_sdk.query()` и формат `tools=` зависит от версии SDK. Если в `claude-agent-sdk==0.1.0` API другой — выровнять по реальному. План закладывает фактический pattern; engineer проверит `pip show claude-agent-sdk` + `python -c "from claude_agent_sdk import query; help(query)"` и поправит этот файл.

- [ ] **Step 4.5: Реализовать server.py**

```python
# agent-runtime/agent_runtime/server.py
import logging

from fastapi import FastAPI, Request

from agent_runtime import agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=f"NanoClaw agent")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/agent/process")
async def process(request: Request):
    payload = await request.json()
    try:
        await agent.handle(payload)
    except Exception:
        logger.exception("agent.handle failed")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

- [ ] **Step 4.6: Запустить — должны пройти**

Run: `cd agent-runtime && pytest tests/test_server.py -v`
Expected: PASS (2 теста).

- [ ] **Step 4.7: Smoke — поднять server локально (без LLM)**

```bash
cd agent-runtime
USER_ID=836757955 CONTAINER_ID=nc-andrey JWT_SECRET=test-secret \
  TOOLS_API_URL=http://localhost:8000 ANTHROPIC_API_KEY=sk-ant-test BOT_TOKEN=fake \
  python -m agent_runtime.server &
SERVER_PID=$!
sleep 2
curl -s http://localhost:8001/health
kill $SERVER_PID
```

Expected: `{"status":"ok"}`

- [ ] **Step 4.8: Коммит**

```bash
git add agent-runtime/agent_runtime/ agent-runtime/tests/
git commit -m "feat(agent-runtime): server + agent (Claude SDK) + telegram_client"
```

---

### Task 5: Dockerfile контейнера

**Files:**
- Create: `agent-runtime/Dockerfile`
- Create: `agent-runtime/.dockerignore`

- [ ] **Step 5.1: Создать Dockerfile**

```dockerfile
# agent-runtime/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_runtime/ ./agent_runtime/

ENV PYTHONUNBUFFERED=1

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8001/health || exit 1

CMD ["python", "-m", "agent_runtime.server"]
```

- [ ] **Step 5.2: Создать .dockerignore**

```
tests/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.git/
```

- [ ] **Step 5.3: Локальная сборка образа**

Run: `cd agent-runtime && docker build -t hv/agent-runtime:dev .`
Expected: успешная сборка, последний layer ~150-200 MB.

- [ ] **Step 5.4: Коммит**

```bash
git add agent-runtime/Dockerfile agent-runtime/.dockerignore
git commit -m "feat(agent-runtime): Dockerfile + .dockerignore"
```

---

### Task 6: docker-compose интеграция nc-andrey

**Files:**
- Modify: `docker-compose.yml` (добавить сервис `nc-andrey`)
- Modify: `docker-compose.prod.yml` (то же)
- Modify: `.env.example` (добавить `ANTHROPIC_API_KEY`)

- [ ] **Step 6.1: Обновить docker-compose.yml**

```yaml
# Добавить в раздел services:
  nc-andrey:
    build:
      context: ./agent-runtime
      dockerfile: Dockerfile
    container_name: nc-andrey
    env_file:
      - .env
    environment:
      - USER_ID=836757955
      - CONTAINER_ID=nc-andrey
      - JWT_SECRET=${NC_ANDREY_JWT_SECRET}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - BOT_TOKEN=${BOT_TOKEN}
      - TOOLS_API_URL=http://bot:8081
      - PACK_DIR=/pack
      - CONTAINER_DIR=/container
    volumes:
      - ./packs/cardiac:/pack:ro
      - ./containers/nc-andrey:/container
    networks:
      - healthvault_network
    depends_on:
      bot:
        condition: service_healthy
    restart: always
```

> **Note:** `bot` сервис уже слушает на 8081 (см. существующий compose). Имя сервиса `nc-andrey` доступно из `bot` по DNS внутри `healthvault_network` — это сетевой адрес для `forward_to_container`.

- [ ] **Step 6.2: То же в docker-compose.prod.yml**

(скопировать тот же блок)

- [ ] **Step 6.3: Добавить переменные в .env.example**

```
# NanoClaw agent containers
ANTHROPIC_API_KEY=sk-ant-...
NC_ANDREY_JWT_SECRET=<32+ hex chars>
```

- [ ] **Step 6.4: Локальный compose-build (без запуска)**

Run: `docker compose -f docker-compose.yml config | grep -A2 nc-andrey`
Expected: вывод сервиса без ошибок валидации.

- [ ] **Step 6.5: Коммит**

```bash
git add docker-compose.yml docker-compose.prod.yml .env.example
git commit -m "feat(infra): nc-andrey service in docker-compose (cardiac pack)"
```

---

### Task 7: Provisioning script — генерация jwt_secret и записи в users

**Files:**
- Create: `scripts/provision_container.py`
- Modify: `database/crud.py` (добавить `provision_container_for_user`)
- Test: `tests/test_provision.py` (новый)

- [ ] **Step 7.1: Failing-тест**

```python
# tests/test_provision.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, User
from database.crud import provision_container_for_user


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(User(telegram_id=836757955, first_name="Andrey", cohort="early_user", pack_name="cardiac", is_active=True))
    s.commit()
    yield s
    s.close()


def test_provision_assigns_jwt_and_container(db):
    user = provision_container_for_user(db, telegram_id=836757955, container_id="nc-andrey", port=8001)
    assert user.jwt_secret and len(user.jwt_secret) >= 32
    assert user.container_id == "nc-andrey"
    assert user.container_port == 8001


def test_provision_idempotent(db):
    u1 = provision_container_for_user(db, telegram_id=836757955, container_id="nc-andrey", port=8001)
    secret = u1.jwt_secret
    u2 = provision_container_for_user(db, telegram_id=836757955, container_id="nc-andrey", port=8001)
    assert u2.jwt_secret == secret  # не перегенерируется без force
```

- [ ] **Step 7.2: Запустить тест — должен упасть**

Run: `pytest tests/test_provision.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 7.3: Реализация в database/crud.py**

```python
# Добавить в database/crud.py
import secrets


def provision_container_for_user(db, telegram_id: int, container_id: str, port: int, force_rotate: bool = False):
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        raise ValueError(f"user {telegram_id} not found")
    if not user.jwt_secret or force_rotate:
        user.jwt_secret = secrets.token_hex(32)
    user.container_id = container_id
    user.container_port = port
    db.commit()
    db.refresh(user)
    return user
```

- [ ] **Step 7.4: CLI скрипт**

```python
# scripts/provision_container.py
"""Provision a NanoClaw container for an existing user.

Usage:
    python scripts/provision_container.py --user-id 836757955 --pack cardiac --port 8001
    python scripts/provision_container.py --user-id 836757955 --pack cardiac --port 8001 --rotate

Side effects:
    - writes jwt_secret/container_id/container_port to users table
    - prints the JWT_SECRET so you can paste into .env (NC_<SHORT>_JWT_SECRET=...)
    - creates containers/nc-<short>/ directory if missing
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal
from database.crud import provision_container_for_user


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--pack", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--rotate", action="store_true")
    args = p.parse_args()

    short = f"nc-{args.user_id}" if args.user_id != 836757955 else "nc-andrey"
    container_dir = ROOT / "containers" / short
    container_dir.mkdir(parents=True, exist_ok=True)
    (container_dir / "memory").mkdir(exist_ok=True)
    (container_dir / "memory" / ".gitkeep").touch()

    db = SessionLocal()
    try:
        user = provision_container_for_user(db, args.user_id, short, args.port, force_rotate=args.rotate)
        print(f"OK: user {user.telegram_id} provisioned")
        print(f"  container_id = {user.container_id}")
        print(f"  container_port = {user.container_port}")
        print(f"  pack_name = {user.pack_name} (must equal '{args.pack}')")
        env_var = f"NC_{short.upper().replace('-', '_')}_JWT_SECRET"
        print(f"\nAdd to .env on server:")
        print(f"  {env_var}={user.jwt_secret}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.5: Запустить тест — должен пройти**

Run: `pytest tests/test_provision.py -v`
Expected: PASS (2 теста).

- [ ] **Step 7.6: Коммит**

```bash
git add database/crud.py scripts/provision_container.py tests/test_provision.py
git commit -m "feat(provisioning): provision_container_for_user + CLI script"
```

---

### Task 8: Onboarding UI polish — inline-кнопки + admin notify

**Files:**
- Modify: `telegram-bot/handlers/onboarding.py`
- Create: `tests/integration/test_onboarding_inline.py`

- [ ] **Step 8.1: Failing-тест на inline-кнопки**

```python
# tests/integration/test_onboarding_inline.py
import pytest
from unittest.mock import patch, AsyncMock

from handlers.onboarding import process_onboarding_message
from database import SessionLocal
from database.models import User


@pytest.fixture
def cleanup():
    db = SessionLocal()
    db.query(User).filter_by(telegram_id=999_001).delete()
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    db.query(User).filter_by(telegram_id=999_001).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_sex_step_uses_inline_keyboard(cleanup):
    """After age step, sex prompt sends inline_keyboard (not reply_keyboard)."""
    payload_name = {"message": {"from": {"id": 999_001, "first_name": "T"}, "chat": {"id": 999_001}, "text": "Test"}}
    payload_age = {"message": {"from": {"id": 999_001}, "chat": {"id": 999_001}, "text": "30"}}

    with patch("handlers.onboarding.send_message", new_callable=AsyncMock) as mock_send:
        await process_onboarding_message(payload_name)  # creates user
        await process_onboarding_message(payload_name)  # name step
        await process_onboarding_message(payload_age)   # age → sex prompt
        last_call = mock_send.await_args_list[-1]
        rm = last_call.kwargs.get("reply_markup") or last_call.args[2] if len(last_call.args) > 2 else None
        assert rm is not None
        assert "inline_keyboard" in rm
```

- [ ] **Step 8.2: Запустить — должен упасть**

Run: `pytest tests/integration/test_onboarding_inline.py -v`
Expected: FAIL (текущий код шлёт `keyboard`, а не `inline_keyboard`).

- [ ] **Step 8.3: Заменить ReplyKeyboard на InlineKeyboard в onboarding.py**

В `telegram-bot/handlers/onboarding.py` шаг `age → sex`:

```python
# Старое:
keyboard = {"keyboard": [["М", "Ж"]], "one_time_keyboard": True, "resize_keyboard": True}
# Новое:
keyboard = {"inline_keyboard": [[
    {"text": "♂ М", "callback_data": "onb_sex:M"},
    {"text": "♀ Ж", "callback_data": "onb_sex:F"},
]]}
```

То же для шага `height → has_garmin`:

```python
keyboard = {"inline_keyboard": [[
    {"text": "Да", "callback_data": "onb_garmin:yes"},
    {"text": "Нет", "callback_data": "onb_garmin:no"},
]]}
```

- [ ] **Step 8.4: Добавить обработку callback_query в onboarding.process_onboarding_message**

```python
# В начале функции:
async def process_onboarding_message(payload: dict) -> None:
    cb = payload.get("callback_query")
    if cb:
        data = cb.get("data", "")
        from_id = cb.get("from", {}).get("id")
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        # Превратить callback в фейковый text-message: 'onb_sex:M' → text='M'
        if data.startswith("onb_sex:"):
            payload = {"message": {"from": {"id": from_id}, "chat": {"id": chat_id}, "text": data.split(":", 1)[1]}}
        elif data.startswith("onb_garmin:"):
            val = data.split(":", 1)[1]
            payload = {"message": {"from": {"id": from_id}, "chat": {"id": chat_id}, "text": "Да" if val == "yes" else "Нет"}}
        else:
            return
        # fallthrough в обычный flow
```

- [ ] **Step 8.5: Admin notification после `done`**

В шаге `has_garmin` после `db.commit()`, перед финальным send_message:

```python
admin_id = int(os.getenv("ADMIN_USER_ID", "895655"))
if admin_id and admin_id != from_id:
    await send_message(
        admin_id,
        f"🆕 Новый пользователь завершил онбординг:\n"
        f"<code>{from_id}</code> — {data.get('name')}, {data.get('age')} лет, {data.get('sex')}, {data.get('height_cm')} см\n\n"
        f"Назначь pack: <code>/assign_pack {from_id} cardiac</code>",
    )
```

- [ ] **Step 8.6: Запустить — должен пройти**

Run: `pytest tests/integration/test_onboarding_inline.py -v`
Expected: PASS.

- [ ] **Step 8.7: Smoke вручную (если на dev DB) — пропустить если на prod**

- [ ] **Step 8.8: Коммит**

```bash
git add telegram-bot/handlers/onboarding.py tests/integration/test_onboarding_inline.py
git commit -m "feat(onboarding): inline keyboards + admin notify on completion"
```

---

### Task 9: `/regenerate_health_token` + `/start` + `/assign_pack` команды

**Files:**
- Modify: `telegram-bot/handlers/commands.py`
- Create: `telegram-bot/handlers/admin.py`
- Create: `tests/test_admin_handlers.py`

- [ ] **Step 9.1: Failing-тест /assign_pack**

```python
# tests/test_admin_handlers.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from handlers.admin import handle_assign_pack


@pytest.mark.asyncio
async def test_assign_pack_requires_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_ID", "895655")
    msg = MagicMock()
    msg.from_user.id = 999_999  # not admin
    msg.text = "/assign_pack 836757955 cardiac"
    msg.answer = AsyncMock()
    await handle_assign_pack(msg)
    msg.answer.assert_awaited_with("⛔ Команда только для админа.")


@pytest.mark.asyncio
async def test_assign_pack_provisions_user(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_ID", "895655")
    msg = MagicMock()
    msg.from_user.id = 895655
    msg.text = "/assign_pack 836757955 cardiac"
    msg.answer = AsyncMock()
    with patch("handlers.admin.provision_container_for_user") as mock_prov:
        mock_prov.return_value = MagicMock(jwt_secret="abc123" * 8, container_id="nc-andrey", container_port=8001)
        await handle_assign_pack(msg)
        mock_prov.assert_called_once()
        msg.answer.assert_awaited()
```

- [ ] **Step 9.2: Реализация admin.py**

```python
# telegram-bot/handlers/admin.py
import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import SessionLocal
from database.crud import provision_container_for_user
from database.models import User

router = Router()
logger = logging.getLogger(__name__)

PACK_TO_PORT = {"cardiac": 8001, "bariatric": 8002, "female-cycle": 8003, "generic": 8010}


@router.message(Command("assign_pack"))
async def handle_assign_pack(msg: Message):
    admin_id = int(os.getenv("ADMIN_USER_ID", "895655"))
    if msg.from_user.id != admin_id:
        await msg.answer("⛔ Команда только для админа.")
        return

    parts = (msg.text or "").split()
    if len(parts) != 3:
        await msg.answer("Использование: /assign_pack <user_id> <pack_name>")
        return

    try:
        target_uid = int(parts[1])
    except ValueError:
        await msg.answer("user_id должен быть числом")
        return
    pack = parts[2]
    if pack not in PACK_TO_PORT:
        await msg.answer(f"pack должен быть одним из: {', '.join(PACK_TO_PORT)}")
        return

    short = "nc-andrey" if target_uid == 836757955 else f"nc-{target_uid}"
    port = PACK_TO_PORT[pack]

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=target_uid).first()
        if not user:
            await msg.answer(f"Пользователь {target_uid} не найден")
            return
        user.pack_name = pack
        db.commit()
        provisioned = provision_container_for_user(db, target_uid, short, port)
        env_var = f"NC_{short.upper().replace('-', '_')}_JWT_SECRET"
        await msg.answer(
            f"✅ Назначено\n"
            f"user_id: <code>{target_uid}</code>\n"
            f"pack: <code>{pack}</code>\n"
            f"container: <code>{short}</code> port {port}\n\n"
            f"Добавь в .env на сервере:\n<code>{env_var}={provisioned.jwt_secret}</code>\n\n"
            f"Затем: docker compose up -d {short}",
            parse_mode="HTML",
        )
    finally:
        db.close()
```

- [ ] **Step 9.3: /regenerate_health_token и /start в commands.py**

Добавить в `telegram-bot/handlers/commands.py`:

```python
import secrets
from aiogram.filters import Command
from database import SessionLocal
from database.models import User


@router.message(Command("regenerate_health_token"))
async def cmd_regenerate_health_token(msg: Message):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=msg.from_user.id).first()
        if not user:
            await msg.answer("Сначала пройди онбординг — нажми /start")
            return
        user.health_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
        db.commit()
        await msg.answer(
            f"🔑 Новый Apple Health токен:\n<code>{user.health_token}</code>\n\n"
            f"Обнови Authorization header в Health Auto Export.",
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.message(Command("start"))
async def cmd_start(msg: Message):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=msg.from_user.id).first()
        if user and user.onboarding_step == "done":
            await msg.answer(
                f"👋 С возвращением, {user.first_name}!\n"
                f"Команды:\n"
                f"/regenerate_health_token — новый токен для Health Auto Export\n"
                f"/dashboard — ссылка на дашборд",
            )
        else:
            # триггерим онбординг через router (он уже умеет)
            await msg.answer("Начинаем онбординг…")
    finally:
        db.close()
```

- [ ] **Step 9.4: Зарегистрировать admin router в bot.py**

Найти в `telegram-bot/bot.py` место где `dp.include_router(...)` и добавить:

```python
from handlers.admin import router as admin_router
dp.include_router(admin_router)
```

- [ ] **Step 9.5: Запустить тесты**

Run: `pytest tests/test_admin_handlers.py -v`
Expected: PASS (2 теста).

- [ ] **Step 9.6: Коммит**

```bash
git add telegram-bot/handlers/admin.py telegram-bot/handlers/commands.py telegram-bot/bot.py tests/test_admin_handlers.py
git commit -m "feat(handlers): /assign_pack (admin), /regenerate_health_token, /start"
```

---

### Task 10: Локальный e2e — поднять nc-andrey, синтетический update, проверить запись в БД

**Files:**
- Create: `scripts/agent_smoke_test.sh`
- Create: `tests/integration/test_container_e2e.py`

- [ ] **Step 10.1: Failing-тест integration**

```python
# tests/integration/test_container_e2e.py
"""End-to-end: synthetic Telegram update → router → container → tools API → DB.

Requires docker compose up: postgres + bot + nc-andrey.
Skipped if SKIP_E2E=1.
"""
import os
import time
import pytest
import httpx

pytestmark = pytest.mark.skipif(os.getenv("SKIP_E2E") == "1", reason="e2e disabled")


@pytest.mark.asyncio
async def test_bp_message_creates_db_row():
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 836757955, "first_name": "Andrey"},
            "chat": {"id": 836757955, "type": "private"},
            "date": int(time.time()),
            "text": "измерил давление 138 на 87 пульс 70",
        },
    }
    async with httpx.AsyncClient() as c:
        r = await c.post("http://localhost:8081/telegram/webhook", json=payload, timeout=60.0)
        assert r.status_code == 200
        assert r.json()["action"] == "forwarded"

    # Дать агенту 30 сек на ответ
    await asyncio_sleep_30()

    # Проверить запись в blood_pressure_logs
    from database import SessionLocal
    db = SessionLocal()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT systolic, diastolic FROM blood_pressure_logs WHERE user_id = :uid ORDER BY measured_at DESC LIMIT 1"),
            {"uid": 836757955},
        ).first()
        assert row is not None
        assert row[0] == 138
        assert row[1] == 87
    finally:
        db.close()


async def asyncio_sleep_30():
    import asyncio
    await asyncio.sleep(30)
```

- [ ] **Step 10.2: Smoke-shell-скрипт**

```bash
#!/usr/bin/env bash
# scripts/agent_smoke_test.sh
# Run AFTER `docker compose up -d` succeeds.
set -euo pipefail

echo "1. Health checks…"
curl -fsS http://localhost:8081/health | grep -q '"ok"' && echo "  bot: ok"
docker exec nc-andrey curl -fsS http://localhost:8001/health | grep -q '"ok"' && echo "  nc-andrey: ok"

echo "2. JWT smoke (через tools_client из контейнера)…"
docker exec nc-andrey python -c "
import asyncio
from agent_runtime.tools_client import ToolsClient
async def main():
    c = ToolsClient()
    p = await c.user_profile()
    print('user_profile:', p)
asyncio.run(main())
"

echo "3. Synthetic Telegram update→router→container…"
curl -fsS -X POST http://localhost:8081/telegram/webhook \
  -H 'Content-Type: application/json' \
  -d '{"update_id":1,"message":{"message_id":1,"from":{"id":836757955,"first_name":"Andrey"},"chat":{"id":836757955,"type":"private"},"date":'$(date +%s)',"text":"измерил давление 138 на 87 пульс 70"}}'
echo
echo "  ↑ ожидаем action=forwarded"

echo "4. Через 30 сек проверь логи: docker logs nc-andrey --tail 50"
echo "5. Проверь запись в БД:"
echo "   docker exec healthvault_postgres psql -U healthvault -d healthvault -c \\"
echo "     \"SELECT systolic, diastolic, measured_at FROM blood_pressure_logs WHERE user_id=836757955 ORDER BY measured_at DESC LIMIT 1;\""
```

```bash
chmod +x scripts/agent_smoke_test.sh
```

- [ ] **Step 10.3: Поднять локально и прогнать**

```bash
# 1. provision Андрея
python scripts/provision_container.py --user-id 836757955 --pack cardiac --port 8001
# (скопируй вывод NC_ANDREY_JWT_SECRET в .env)

# 2. compose up
docker compose up -d --build postgres bot nc-andrey

# 3. smoke
./scripts/agent_smoke_test.sh
```

Expected:
- bot: ok, nc-andrey: ok
- user_profile вернул JSON с cohort=early_user, pack_name=cardiac
- action=forwarded
- через 30 сек в БД появилась строка 138/87

- [ ] **Step 10.4: Запустить integration-тест**

Run: `pytest tests/integration/test_container_e2e.py -v -s`
Expected: PASS (если compose up).

- [ ] **Step 10.5: Коммит**

```bash
git add scripts/agent_smoke_test.sh tests/integration/test_container_e2e.py
git commit -m "test(e2e): nc-andrey smoke + integration test"
```

---

### Task 11: Deploy на prod-сервер

**Files:**
- Create: `docs/SPRINT_1B_DEPLOY.md`

- [ ] **Step 11.1: Бэкап БД**

```bash
ssh root@116.203.213.137 "/opt/healthvault/scripts/auto_backup.sh"
ssh root@116.203.213.137 "ls -la /opt/healthvault/backups/ | tail -3"
```

Expected: новый файл `healthvault_db_<сегодня>.sql.gz`.

- [ ] **Step 11.2: Push кода и pull на сервере**

```bash
git push origin main  # либо мердж sprint/1b-containers → main → push
ssh root@116.203.213.137 "cd /opt/healthvault && git pull"
```

- [ ] **Step 11.3: Provision Андрея на prod**

```bash
ssh root@116.203.213.137 "cd /opt/healthvault && python scripts/provision_container.py --user-id 836757955 --pack cardiac --port 8001"
# Скопируй NC_ANDREY_JWT_SECRET= в /opt/healthvault/.env
```

- [ ] **Step 11.4: Добавить ANTHROPIC_API_KEY в .env на сервере**

```bash
ssh root@116.203.213.137 "grep -q '^ANTHROPIC_API_KEY=' /opt/healthvault/.env || echo 'ANTHROPIC_API_KEY=<paste>' >> /opt/healthvault/.env"
```

- [ ] **Step 11.5: Build + up nc-andrey**

```bash
ssh root@116.203.213.137 "cd /opt/healthvault && docker compose -f docker-compose.prod.yml build nc-andrey && docker compose -f docker-compose.prod.yml up -d nc-andrey"
```

- [ ] **Step 11.6: Health-чек**

```bash
ssh root@116.203.213.137 "docker exec nc-andrey curl -fsS http://localhost:8001/health"
ssh root@116.203.213.137 "docker logs nc-andrey --tail 30"
```

Expected: `{"status":"ok"}`, в логах нет крашей, видно «Uvicorn running on http://0.0.0.0:8001».

- [ ] **Step 11.7: Реальный smoke от Андрея**

(вне Claude — попросить Андрея написать в `@HealthVault_bot`: «измерил давление 138 на 87»)

Проверка:
```bash
ssh root@116.203.213.137 "docker logs nc-andrey --tail 30 | grep -i bp"
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \\
  \"SELECT systolic, diastolic, measured_at FROM blood_pressure_logs WHERE user_id=836757955 ORDER BY measured_at DESC LIMIT 1;\""
```

Expected: строка с 138/87 + временем «только что».

- [ ] **Step 11.8: Регрессия — Александр и Ника**

Попросить Сашу прислать фото еды → проверить что photo handler сработал (legacy fallback).
Попросить Нику отправить текст еды → проверить что legacy bot обработал (у неё нет container_id).

- [ ] **Step 11.9: SPRINT_1B_DEPLOY.md**

```markdown
# Sprint 1b — Deploy notes

## Что задеплоено
- packs/cardiac (CLAUDE.md + 4 skills)
- containers/nc-andrey (per-user override)
- agent-runtime/ образ → docker hub local
- nc-andrey сервис в docker-compose.prod.yml на порту 8001 (internal)
- Onboarding inline-кнопки + admin /assign_pack + /regenerate_health_token

## Endpoint-карта
- `POST /telegram/webhook` — bot:8081 (Telegram → router)
- `POST /agent/process` — nc-andrey:8001 (router → агент)
- `POST /api/agent/log_*` — bot:8081 (агент → tools API, JWT)

## Чек-лист на новый pack/контейнер
1. `python scripts/provision_container.py --user-id <X> --pack <P> --port <PORT>`
2. Скопировать `NC_<SHORT>_JWT_SECRET=...` в `.env`
3. Добавить блок сервиса в `docker-compose.prod.yml` (по образцу `nc-andrey`)
4. `docker compose -f docker-compose.prod.yml up -d --build nc-<short>`
5. Smoke: `./scripts/agent_smoke_test.sh`

## Troubleshooting
- nc-andrey не стартует → `docker logs nc-andrey` (чаще: missing env)
- 401 от tools API → JWT_SECRET в env контейнера ≠ users.jwt_secret в БД (rerun provision)
- 403 container_id mismatch → CONTAINER_ID env ≠ users.container_id
- Агент молчит → ANTHROPIC_API_KEY не задан или нет квоты
```

- [ ] **Step 11.10: Коммит**

```bash
git add docs/SPRINT_1B_DEPLOY.md
git commit -m "docs: SPRINT_1B_DEPLOY notes"
```

---

### Task 12: AI_CHANGELOG + todo.md + регрессия

**Files:**
- Modify: `docs/ai_context/AI_CHANGELOG.md`
- Modify: `todo.md`

- [ ] **Step 12.1: Прогнать полный test suite**

```bash
pytest -v --tb=short
cd agent-runtime && pytest -v
```

Expected: все unit + integration зелёные. Если что-то упало — фиксить здесь же, не отправлять в новый task.

- [ ] **Step 12.2: AI_CHANGELOG запись**

В `docs/ai_context/AI_CHANGELOG.md` — добавить **сверху** (после строки `---`):

```markdown
## 2026-05-XX — Sprint 1b: Onboarding UI + nc-andrey container

**Задача:** Поднять первый NanoClaw-контейнер для Андрея с pack:cardiac, доделать онбординг (inline-кнопки, admin notify, /assign_pack, /regenerate_health_token).

**Что сделано:**
1. `packs/cardiac/` — CLAUDE.md + 4 SKILL.md (log-bp, log-meds, query-kb, dashboard-summary).
2. `containers/nc-andrey/CLAUDE.md` — per-user override с диагнозами Андрея.
3. `agent-runtime/` — Python-сервис (Claude Agent SDK + FastAPI), Dockerfile, конфиг через env.
4. `agent-runtime/agent_runtime/tools_client.py` — JWT-аутентифицированный клиент к 7 endpoint'ам Tools API.
5. `docker-compose.{yml,prod.yml}` — добавлен сервис `nc-andrey` (порт 8001, монтирует pack:ro и container:rw).
6. `scripts/provision_container.py` — CLI для генерации jwt_secret + записи container_id/port в users.
7. `telegram-bot/handlers/onboarding.py` — inline-кнопки на шагах sex/has_garmin, обработка callback_query, admin notify после `done`.
8. `telegram-bot/handlers/admin.py` — `/assign_pack <uid> <pack>` (admin-only).
9. `telegram-bot/handlers/commands.py` — `/start`, `/regenerate_health_token`.
10. `tests/integration/test_container_e2e.py` — синтетический update → проверка записи в blood_pressure_logs.

**Тесты:** N unit + M integration (включая новые) — all green.

**Smoke на prod:** Андрей написал «измерил давление 138/87» → агент ответил → запись в БД.

**Файлы:** `packs/cardiac/`, `containers/nc-andrey/`, `agent-runtime/`, `docker-compose.yml`, `docker-compose.prod.yml`, `scripts/provision_container.py`, `telegram-bot/handlers/{onboarding,admin,commands}.py`, `tests/test_admin_handlers.py`, `tests/test_provision.py`, `tests/integration/test_onboarding_inline.py`, `tests/integration/test_container_e2e.py`, `docs/SPRINT_1B_DEPLOY.md`.
```

- [ ] **Step 12.3: todo.md статус**

Найти строку про Sprint 1a (~510) и добавить ниже:

```markdown
- [x] **🚀 Sprint 1b — onboarding UI + nc-andrey (XX.05.2026, выполнено)**: pack:cardiac, контейнер nc-andrey в docker-compose, inline-кнопки в онбординге, /assign_pack admin-команда, /regenerate_health_token, e2e smoke green. Андрей в продакшене с агентом. Sprint 2: остальные packs (bariatric, female-cycle), KB-pipeline, BYOK.
```

- [ ] **Step 12.4: Финальный коммит**

```bash
git add docs/ai_context/AI_CHANGELOG.md todo.md
git commit -m "docs: AI_CHANGELOG + todo Sprint 1b done"
```

- [ ] **Step 12.5: Push (или PR)**

Если работали в worktree:
```bash
git push origin sprint/1b-containers
gh pr create --title "Sprint 1b: onboarding UI + nc-andrey container" --body "$(cat <<'EOF'
## Summary
- packs/cardiac готов (CLAUDE.md + 4 skills)
- agent-runtime контейнер на Claude Agent SDK
- nc-andrey запущен в проде, Андрей общается с агентом end-to-end
- Onboarding wizard polish (inline keyboards), /assign_pack, /regenerate_health_token

## Test plan
- [ ] Все unit-тесты (pytest -v)
- [ ] Integration (test_container_e2e.py) при поднятом compose
- [ ] Андрей: real BP message → DB row
- [ ] Регрессия: Саша фото еды, Ника текст еды — legacy path
EOF
)"
```

Иначе:
```bash
git push origin main
```

---

## Self-review checklist (выполнить перед merge)

- [ ] Все ссылки в плане ведут на реальные файлы (нет «TBD»).
- [ ] Каждый таск заканчивается коммитом.
- [ ] AI_CHANGELOG обновлён.
- [ ] `pytest` зелёный.
- [ ] `docker compose ps` показывает `nc-andrey` healthy.
- [ ] Андрей реально получил ответ от агента.
- [ ] Регрессия Саши и Ники не сломана.
- [ ] Нет hardcoded секретов в репо (jwt_secret только в env, ANTHROPIC_API_KEY только в .env.production).
