# Igor Botkin Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подключить Игоря (telegram_id 830908046) к BotkinClaw как family/respiratory_allergic, оставить переиспользуемый pipeline для подключения мамы и других семейных юзеров.

**Architecture:** CLI-скрипт `scripts/onboard_family_user.py` оркестрирует пакет `scripts/onboard/` (валидация KB, LLM-генерация персоны, scp/psql деплой, welcome). Декларативный pack registry в `core/packs.py`. Шаблон промпта в `scripts/server/agent_prompts/templates/`. Никаких изменений в `agent_tools_api.py` и `agent_chat.py` — они уже умеют per-user KB.

**Tech Stack:** Python 3.11, pytest, argparse, string.Template, Anthropic Messages API (claude-sonnet-4-6 → 4-5 fallback), sshpass+scp, psql через docker exec, Telegram Bot API requests.

**Dev environment:**
- Project root: `/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin/`
- Spec: [docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md](docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md)
- Server: `root@116.203.213.137:/opt/healthvault/`, password via `.env` `SERVER_PASSWORD` или sshpass-команда из `scripts/fetch_remote_nutrition.sh`
- DB inside container: `docker exec healthvault_postgres psql -U healthvault -d healthvault`
- Family folder Igor: `~/.../FamilyHealth/Игорь Лысковский — Здоровье/knowledge_base.json` (52 KB)
- Anthropic API key: в `.env` как `ANTHROPIC_API_KEY`
- Use a worktree for implementation: see superpowers:using-git-worktrees skill before starting Task 1.

---

## File Structure

| Файл | Создаётся / Изменяется | Ответственность |
|---|---|---|
| `core/packs.py` | Create | Декларативный реестр Pack-объектов |
| `tests/test_packs.py` | Create | Тесты реестра |
| `scripts/server/agent_prompts/templates/family_active_coach.md` | Create | Markdown-шаблон с {placeholder}'ами |
| `scripts/onboard/__init__.py` | Create | Пустой, делает пакет |
| `scripts/onboard/kb_validator.py` | Create | Валидация структуры knowledge_base.json |
| `scripts/onboard/persona_generator.py` | Create | LLM-вызов → три персональных блока |
| `scripts/onboard/server_deployer.py` | Create | scp KB + psql UPDATE с rollback'ом |
| `scripts/onboard/welcome_sender.py` | Create | Telegram Bot API sendMessage + лог в БД |
| `scripts/onboard/snapshot.py` | Create | Чтение/запись `data/onboarding_snapshots/` |
| `scripts/onboard_family_user.py` | Create | CLI оркестратор (argparse) |
| `tests/test_onboard_kb_validator.py` | Create | Тесты валидации |
| `tests/test_onboard_persona_generator.py` | Create | Тесты с моком Anthropic |
| `tests/test_onboard_server_deployer.py` | Create | Тесты с моком subprocess |
| `tests/test_onboard_cli.py` | Create | CLI integration tests (dry-run, force, snapshot) |
| `scripts/server/agent_prompts/igor.md` | Create (артефакт) | Финальный персональный промпт Игоря |
| `docs/operations/onboard-family-user.md` | Create | Runbook для будущих юзеров |
| `docs/ai_context/AI_CHANGELOG.md` | Modify | Запись 22.05.2026 |
| `data/onboarding_snapshots/.gitignore` | Create | Игнор-файл (снапшоты в гит не идут) |

**Total:** 15 новых файлов + 1 модификация.

---

## Task 1: Pack registry — `core/packs.py`

**Files:**
- Create: `core/packs.py`
- Create: `tests/test_packs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_packs.py
"""Тесты для декларативного реестра packs."""
import pytest

from core.packs import PACKS, Pack, get_pack


def test_pack_is_frozen_dataclass():
    """Pack — immutable. Попытка изменить должна падать."""
    p = PACKS["generic"]
    with pytest.raises((AttributeError, TypeError)):
        p.name = "modified"


def test_all_packs_present():
    """Все известные packs зарегистрированы."""
    assert set(PACKS.keys()) == {
        "bariatric",
        "cardiac",
        "generic",
        "respiratory_allergic",
    }


def test_respiratory_allergic_pack_shape():
    """Новый pack для Игоря — корректная структура."""
    p = get_pack("respiratory_allergic")
    assert p.name == "respiratory_allergic"
    assert "asthma_allergy_panel" in p.focus_areas
    assert "vitamin_d" in p.focus_areas
    assert "tick_antibodies" in p.focus_areas
    assert "vitamin_d_trend" in p.dashboard_blocks
    assert "allergy_history" in p.dashboard_blocks


def test_get_pack_unknown_raises():
    """Неизвестный pack → ValueError с понятным сообщением."""
    with pytest.raises(ValueError) as exc_info:
        get_pack("does_not_exist")
    assert "does_not_exist" in str(exc_info.value)
    assert "respiratory_allergic" in str(exc_info.value)  # список available


def test_existing_packs_unchanged():
    """Регрессия: bariatric/cardiac/generic не сломались."""
    assert get_pack("bariatric").name == "bariatric"
    assert get_pack("cardiac").name == "cardiac"
    assert get_pack("generic").name == "generic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin" && python3 -m pytest tests/test_packs.py -v`
Expected: ImportError (core.packs не существует)

- [ ] **Step 3: Implement `core/packs.py`**

```python
"""Pack registry — декларативный список фокусных профилей.

Pack — это тэг направления коучинга в system_prompt + блоки дашборда + шаблон
отчёта. Захардкожен как Python-модуль (а не БД/JSON) потому что dashboard_blocks
и report_template — это код, не data.

Используется:
- scripts/onboard_family_user.py (валидация при --pack X)
- ...будущее: core/reports/* для выбора блоков в отчёте
- ...будущее: dashboard_generator для блоков дашборда

См. design: docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Pack:
    """Фокусный профиль здоровья."""

    name: str
    description: str
    focus_areas: tuple[str, ...]
    dashboard_blocks: tuple[str, ...]
    report_template: Optional[str]  # путь к Jinja2 шаблону отчёта; None если ещё нет


PACKS: dict[str, Pack] = {
    "bariatric": Pack(
        name="bariatric",
        description="Снижение веса + метаболика",
        focus_areas=("weight", "metabolic_panel", "blood_pressure", "macros"),
        dashboard_blocks=("weight_trend", "calorie_balance", "macros"),
        report_template=None,
    ),
    "cardiac": Pack(
        name="cardiac",
        description="Кардиометаболический риск",
        focus_areas=("blood_pressure", "lipids", "ecg", "physical_activity"),
        dashboard_blocks=("bp_trend", "lipids_panel", "activity"),
        report_template=None,
    ),
    "generic": Pack(
        name="generic",
        description="Общий профиль без специфического фокуса",
        focus_areas=("general_screening",),
        dashboard_blocks=("weight_trend", "activity"),
        report_template=None,
    ),
    "respiratory_allergic": Pack(
        name="respiratory_allergic",
        description="Астма + аллерго-история + регулярный скрининг (КЭ-антитела, витD)",
        focus_areas=(
            "asthma_allergy_panel",
            "vitamin_d",
            "pollen_seasonal",
            "tick_antibodies",
        ),
        dashboard_blocks=("vitamin_d_trend", "allergy_history", "tick_antibodies"),
        report_template=None,
    ),
}


def get_pack(name: str) -> Pack:
    """Получить Pack по имени, иначе ValueError со списком доступных."""
    if name not in PACKS:
        raise ValueError(
            f"Unknown pack: {name!r}. Available: {sorted(PACKS.keys())}"
        )
    return PACKS[name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_packs.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add core/packs.py tests/test_packs.py
git commit -m "core: pack registry — declarative Pack dataclass + respiratory_allergic

Reusable directory of focus-profiles for agent system_prompt customization and
future report/dashboard branching. Frozen dataclass + lookup helper with explicit
error message listing available packs."
```

---

## Task 2: Snapshot helper — `scripts/onboard/snapshot.py`

**Files:**
- Create: `scripts/onboard/__init__.py` (пустой)
- Create: `scripts/onboard/snapshot.py`
- Create: `data/onboarding_snapshots/.gitignore`
- Create: `tests/test_onboard_snapshot.py`

- [ ] **Step 1: Create empty package marker and gitignore**

Run:
```bash
mkdir -p scripts/onboard data/onboarding_snapshots
touch scripts/onboard/__init__.py
printf "*\n!.gitignore\n" > data/onboarding_snapshots/.gitignore
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_onboard_snapshot.py
"""Тесты snapshot helper'а — фиксации состояния юзера до изменений."""
import json
from pathlib import Path

import pytest

from scripts.onboard.snapshot import (
    UserSnapshot,
    save_snapshot,
    load_latest_snapshot,
)


def test_save_snapshot_writes_json(tmp_path):
    snap = UserSnapshot(
        telegram_id=999,
        cohort="external",
        pack_name="generic",
        agent_system_prompt="",
        kb_existed_on_server=False,
    )
    path = save_snapshot(snap, snapshots_dir=tmp_path)

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["telegram_id"] == 999
    assert data["cohort"] == "external"
    assert data["kb_existed_on_server"] is False
    assert "timestamp" in data


def test_load_latest_picks_most_recent(tmp_path):
    """Если несколько снапшотов, берём последний по timestamp."""
    snap_a = UserSnapshot(999, "external", "generic", "", False)
    snap_b = UserSnapshot(999, "family", "respiratory_allergic", "promptB", True)

    save_snapshot(snap_a, snapshots_dir=tmp_path)
    # симуляция времени — пишем второй с явно более поздним именем
    import time

    time.sleep(0.01)
    save_snapshot(snap_b, snapshots_dir=tmp_path)

    latest = load_latest_snapshot(telegram_id=999, snapshots_dir=tmp_path)
    assert latest.cohort == "family"
    assert latest.pack_name == "respiratory_allergic"


def test_load_latest_returns_none_when_missing(tmp_path):
    assert load_latest_snapshot(telegram_id=12345, snapshots_dir=tmp_path) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_snapshot.py -v`
Expected: ImportError

- [ ] **Step 4: Implement snapshot.py**

```python
# scripts/onboard/snapshot.py
"""Snapshot состояния юзера в БД до изменений — для rollback'а."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Default — относительно корня проекта; CLI/тесты могут переопределить.
DEFAULT_SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "onboarding_snapshots"


@dataclass
class UserSnapshot:
    telegram_id: int
    cohort: str
    pack_name: str
    agent_system_prompt: str
    kb_existed_on_server: bool


def save_snapshot(snap: UserSnapshot, *, snapshots_dir: Optional[Path] = None) -> Path:
    """Записать snapshot. Имя файла: <tid>_<isoformat>.json (sortable)."""
    snapshots_dir = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    path = snapshots_dir / f"{snap.telegram_id}_{timestamp}.json"
    payload = asdict(snap)
    payload["timestamp"] = timestamp
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def load_latest_snapshot(
    *, telegram_id: int, snapshots_dir: Optional[Path] = None
) -> Optional[UserSnapshot]:
    """Вернуть самый свежий snapshot для юзера, либо None если нет."""
    snapshots_dir = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    if not snapshots_dir.exists():
        return None
    candidates = sorted(snapshots_dir.glob(f"{telegram_id}_*.json"))
    if not candidates:
        return None
    data = json.loads(candidates[-1].read_text())
    data.pop("timestamp", None)
    return UserSnapshot(**data)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_snapshot.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/onboard/__init__.py scripts/onboard/snapshot.py \
        data/onboarding_snapshots/.gitignore tests/test_onboard_snapshot.py
git commit -m "onboard: snapshot helper for rollback safety

Persist UserSnapshot (cohort, pack, prompt, server-kb presence) to
data/onboarding_snapshots/ before any change. load_latest_snapshot used by
--unenroll and automatic rollback paths."
```

---

## Task 3: KB validator — `scripts/onboard/kb_validator.py`

**Files:**
- Create: `scripts/onboard/kb_validator.py`
- Create: `tests/test_onboard_kb_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_onboard_kb_validator.py
"""Валидация knowledge_base.json перед заливкой на сервер."""
import json

import pytest

from scripts.onboard.kb_validator import validate_kb, KbValidationError


def _write_kb(tmp_path, data):
    p = tmp_path / "knowledge_base.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


def test_valid_kb_passes(tmp_path):
    kb = {
        "blood_tests": [
            {"date": "2025-05-08", "values": {"vitamin_d": 35.4, "ferritin": 90}}
        ],
        "diagnoses": ["J45 Asthma"],
    }
    p = _write_kb(tmp_path, kb)
    summary = validate_kb(p)
    assert summary.blood_tests_count == 1
    assert summary.size_bytes > 0


def test_kb_with_markers_field_raises(tmp_path):
    """Регрессия: standard_kb_values_field memory — должно быть 'values', не 'markers'."""
    kb = {"blood_tests": [{"date": "2025-05-08", "markers": {"vitamin_d": 35.4}}]}
    p = _write_kb(tmp_path, kb)
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "values" in str(exc.value)  # explain the standard


def test_kb_completely_empty_raises(tmp_path):
    """Нет ни анализов, ни ECG, ни диагнозов — заливать нечего."""
    p = _write_kb(tmp_path, {})
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "empty" in str(exc.value).lower() or "no data" in str(exc.value).lower()


def test_kb_too_large_raises(tmp_path):
    p = tmp_path / "huge.json"
    # 2 MB файл — над лимитом 1 MB
    p.write_text("{" + ('"x":"' + "a" * 1000 + '",') * 2100 + '"end":1}')
    with pytest.raises(KbValidationError) as exc:
        validate_kb(p)
    assert "size" in str(exc.value).lower() or "large" in str(exc.value).lower()


def test_kb_invalid_json_raises(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json}")
    with pytest.raises(KbValidationError):
        validate_kb(p)


def test_kb_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_kb(tmp_path / "nonexistent.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_kb_validator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement kb_validator.py**

```python
# scripts/onboard/kb_validator.py
"""Валидация structure & sanity у knowledge_base.json перед заливкой."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_KB_SIZE_BYTES = 1_048_576  # 1 MB


class KbValidationError(ValueError):
    """KB не прошёл валидацию."""


@dataclass
class KbSummary:
    size_bytes: int
    blood_tests_count: int
    medical_records_count: int
    diagnoses_count: int


def _check_no_markers_field(blood_tests: list[dict[str, Any]]) -> None:
    """Memory standard_kb_values_field: биомаркеры идут в 'values', не 'markers'."""
    for i, bt in enumerate(blood_tests):
        if "markers" in bt and "values" not in bt:
            raise KbValidationError(
                f"blood_tests[{i}] uses legacy field 'markers' — must be 'values' "
                f"(see memory: standard_kb_values_field). Migrate the KB first."
            )


def validate_kb(path: Path) -> KbSummary:
    """Прочитать и проверить KB. Вернуть summary либо бросить KbValidationError."""
    if not path.exists():
        raise FileNotFoundError(f"KB not found: {path}")

    size = path.stat().st_size
    if size > MAX_KB_SIZE_BYTES:
        raise KbValidationError(
            f"KB too large: {size} bytes > {MAX_KB_SIZE_BYTES} limit. "
            "Likely a parsing bug — investigate before uploading."
        )

    try:
        kb = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise KbValidationError(f"KB is not valid JSON: {e}") from e

    blood_tests = kb.get("blood_tests", []) or []
    medical_records = kb.get("medical_records", []) or []
    ecg = kb.get("ecg", []) or []
    diagnoses = kb.get("diagnoses", []) or []

    if not (blood_tests or medical_records or ecg or diagnoses):
        raise KbValidationError(
            "KB is empty — no blood_tests/medical_records/ecg/diagnoses. "
            "Nothing to upload."
        )

    _check_no_markers_field(blood_tests)

    return KbSummary(
        size_bytes=size,
        blood_tests_count=len(blood_tests),
        medical_records_count=len(medical_records),
        diagnoses_count=len(diagnoses),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_kb_validator.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/onboard/kb_validator.py tests/test_onboard_kb_validator.py
git commit -m "onboard: KB validator — size, schema, 'values' field standard

Sanity-checks knowledge_base.json before scp to server. Enforces the
'values' (not 'markers') convention from memory standard_kb_values_field."
```

---

## Task 4: Prompt template — `family_active_coach.md`

**Files:**
- Create: `scripts/server/agent_prompts/templates/family_active_coach.md`

- [ ] **Step 1: Create the template directory if missing**

Run:
```bash
mkdir -p scripts/server/agent_prompts/templates
```

- [ ] **Step 2: Write the template**

Write to `scripts/server/agent_prompts/templates/family_active_coach.md`:

```markdown
# Botkin Agent — $name

Ты — личный AI-агент $name по теме здоровья. Часть проекта Botkin (botkin.health). Канал: Telegram @Botkin_md_bot. Подключил Александр Лысковский.

## Пользователь

**$full_name** — $age (рожд. $birth_date). $location.
Pack: `$pack_name` ($pack_description). Cohort: `$cohort`, **$cohort_relationship**.
$bio_line

## Стиль обращения

$communication_style

## Главное про пользователя — рамка для интерпретации всего

$framing_block

### Хронические диагнозы

$chronic_block

### Открытые красные флаги (то, что обсуждаем)

$open_questions_block

## Текущая терапия

$therapy_block

## Источники данных

**Полный KB:** доступен через `get_kb_value(path=...)`. У этого юзера в KB: $kb_sections_list.

**Биомаркеры в БД (blood_tests):** доступ через `get_recent_biomarkers(test_type=..., months=...)`. Синхронизированы blood_tests из KB.

**Анамнез из переписки и устных:** хранится в файле `chat_anamnesis.md` (на стороне Александра).

## Фокус-темы (определены pack=$pack_name)

$focus_areas_block

## Контекст для типичных вопросов

$typical_questions_block

## Базовые правила работы

- Отвечай коротко по умолчанию (1-3 предложения), без таблиц/заголовков. Длинно — только если просили или вопрос реально многофакторный (см. memory: feedback_agent_response_length).
- Опирайся на доказательную медицину (ESC, AHA, NCCN, ADA, российские КР Минздрава, PubMed). Не выдумывай.
- Если нужны данные — используй tools (get_recent_biomarkers, get_kb_value, get_recent_meals, get_recent_bp, get_recent_sleep, get_recent_supplements). Не угадывай.
- При серьёзных симптомах — направляй к врачу, не заменяй его.
- Помни про privacy: данные пользователя приватны, не упоминай его в контексте других семейных юзеров.
```

**Note:** Все `$placeholder` подставляются через `string.Template.safe_substitute()` в Task 5. Использование `$name` (а не `${name}`) — стандарт string.Template.

- [ ] **Step 3: Verify template parses correctly**

Run:
```bash
python3 -c "
from string import Template
from pathlib import Path
t = Template(Path('scripts/server/agent_prompts/templates/family_active_coach.md').read_text())
result = t.safe_substitute(name='TEST')
print('OK' if '\$' not in result.split('# Botkin Agent — TEST')[0] else 'PROBLEM')
print('placeholders:', sorted(set([w[1:].split('.')[0].rstrip(',!?:;') for w in t.template.split() if w.startswith('\$')])))
"
```
Expected: `OK` + список placeholder'ов.

- [ ] **Step 4: Commit**

```bash
git add scripts/server/agent_prompts/templates/family_active_coach.md
git commit -m "onboard: family_active_coach.md prompt template

Markdown template with \$name/\$age/etc placeholders for string.Template
substitution. Caracas extracted from pavel.md, generalized."
```

---

## Task 5: Persona generator — `scripts/onboard/persona_generator.py`

**Files:**
- Create: `scripts/onboard/persona_generator.py`
- Create: `tests/test_onboard_persona_generator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_onboard_persona_generator.py
"""Persona generator — LLM-вызов для трёх персональных блоков промпта."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.onboard.persona_generator import (
    PersonaInput,
    PersonaBlocks,
    generate_persona,
    render_prompt,
)


@pytest.fixture
def sample_input():
    return PersonaInput(
        name="Игорь",
        full_name="Лысковский Игорь Александрович",
        age="21 год",
        birth_date="2004-08-15",
        location="Москва",
        cohort="family",
        cohort_relationship="сын Александра",
        pack_name="respiratory_allergic",
        bio_line="Студент. Аллергия на пыль, поллиноз. Регулярный скрининг КЭ-вакцины.",
        kb_json={
            "blood_tests": [
                {"date": "2025-05-08", "values": {"vitamin_d": 35.4}},
            ],
            "diagnoses": ["J45 Asthma intermittens"],
        },
        profile_md="Профиль Игоря: астма с детства, поллиноз, ежегодная вакцина КЭ.",
        style="ty",
    )


def test_render_prompt_substitutes_all_placeholders(sample_input, tmp_path):
    """После подстановки в шаблоне не остаётся '$' плейсхолдеров."""
    template_path = Path("scripts/server/agent_prompts/templates/family_active_coach.md")
    blocks = PersonaBlocks(
        framing="<framing>",
        chronic="<chronic>",
        open_questions="<open_questions>",
        therapy="<therapy>",
        focus_areas="<focus_areas>",
        typical_questions="<typical_questions>",
    )
    rendered = render_prompt(sample_input, blocks, template_path=template_path)
    # Никаких неподставленных $placeholder
    import re
    leftovers = re.findall(r"\$[a-z_]+", rendered)
    assert not leftovers, f"Unsubstituted placeholders: {leftovers}"
    # Имя подставлено
    assert "Игорь" in rendered
    # Pack описание есть
    assert "respiratory_allergic" in rendered


def test_generate_persona_calls_anthropic(sample_input, monkeypatch):
    """LLM-вызов идёт через anthropic API с правильной моделью."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "framing": "21-летний с астмой...",
                    "chronic": "- J45 Asthma intermittens",
                    "open_questions": "- Витамин D 35 — на нижней границе",
                    "therapy": "Беродуал по требованию",
                    "focus_areas": "Витамин D, аллерго-панель, КЭ",
                    "typical_questions": "Про кошек: реакция на эпителий...",
                }),
            }
        ]
    }
    with patch("scripts.onboard.persona_generator.requests.post", return_value=fake_response) as mock_post:
        blocks = generate_persona(sample_input)
    assert mock_post.called
    args, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["model"] == "claude-sonnet-4-6"
    assert blocks.framing.startswith("21-летний")
    assert "J45" in blocks.chronic


def test_generate_persona_fallback_on_overload(sample_input, monkeypatch):
    """529 на 4.6 → retry на 4.5."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    overload = MagicMock(status_code=529, text="overloaded")
    success = MagicMock(status_code=200)
    success.json.return_value = {
        "content": [{"type": "text", "text": json.dumps({
            "framing": "x", "chronic": "x", "open_questions": "x",
            "therapy": "x", "focus_areas": "x", "typical_questions": "x"
        })}]
    }
    responses = [overload, overload, success]  # 529, 529 (quick retry), 200 on fallback

    with patch("scripts.onboard.persona_generator.requests.post", side_effect=responses) as mock_post:
        with patch("scripts.onboard.persona_generator.time.sleep"):  # speed up
            blocks = generate_persona(sample_input)
    # Третий вызов — на fallback модели
    last_payload = mock_post.call_args_list[-1].kwargs["json"]
    assert last_payload["model"] == "claude-sonnet-4-5"
    assert blocks.framing == "x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_persona_generator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement persona_generator.py**

```python
# scripts/onboard/persona_generator.py
"""LLM-генерация персональных блоков для system_prompt.

Шесть блоков выводятся одним структурированным вызовом Claude'а:
- framing: рамка для интерпретации всего
- chronic: список диагнозов с формулировками
- open_questions: красные флаги, что сейчас обсуждаем
- therapy: текущая терапия
- focus_areas: что важно для pack
- typical_questions: контекстные ответы на типичные ситуации

Модель: claude-sonnet-4-6 с fallback на 4-5 при 529/503/429 (паттерн из core/agent_chat.py).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from string import Template

import requests

from core.packs import get_pack

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-4-6"
FALLBACK_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4000
REQUEST_TIMEOUT = 60
QUICK_RETRY_SLEEP = 0.7


@dataclass
class PersonaInput:
    name: str  # короткое имя — "Игорь"
    full_name: str  # полное — "Лысковский Игорь Александрович"
    age: str  # "21 год" — словами
    birth_date: str
    location: str
    cohort: str
    cohort_relationship: str  # "сын Александра"
    pack_name: str
    bio_line: str
    kb_json: dict  # полный knowledge_base.json
    profile_md: str  # содержимое PROFILE.md
    style: str  # "ty" или "vy"


@dataclass
class PersonaBlocks:
    framing: str
    chronic: str
    open_questions: str
    therapy: str
    focus_areas: str
    typical_questions: str


_GENERATION_INSTRUCTION = """\
Ты помогаешь сгенерировать персональные блоки для system_prompt медицинского AI-агента.

Тебе дан профиль пользователя (структурированный knowledge_base.json + PROFILE.md),
его pack ({pack_name}, описание: {pack_description}), стиль обращения {style_human}.

Сгенерируй СТРОГО JSON-объект с шестью полями:
- framing: 2-3 абзаца — главная рамка интерпретации (кто этот пациент, что у него
  основное, что сейчас в фокусе). Без списков, проза.
- chronic: маркированный список диагнозов с МКБ-кодами (если есть) и кратким
  пояснением. Если диагнозов нет — пиши "Хронических диагнозов в KB нет".
- open_questions: 1-5 пунктов про "красные флаги" / что сейчас под вниманием.
  Если ничего — пиши "На момент онбординга открытых красных флагов в KB не зафиксировано".
- therapy: текущая терапия (препараты + добавки). Если в KB нет — пиши
  "Постоянной терапии в KB нет. Уточни у пользователя в первом разговоре."
- focus_areas: 2-4 предложения про focus-зоны под этот pack. Привязывай к
  реальным данным юзера.
- typical_questions: 3-6 примеров вопросов, которые юзер может задать, с краткими
  гайдами как отвечать (например, "Про витамин D — назови последнее значение
  и тренд за 2-3 точки").

ВАЖНО:
- {style_instruction}
- Без выдумок. Только факты из KB и PROFILE.md.
- Если данных мало — честно отмечай ("при первом разговоре уточни").
- Только Markdown в значениях. Без HTML.
- Ответ — голый JSON без обёртки ```json, без префиксных фраз.
"""


def _build_generation_messages(inp: PersonaInput) -> tuple[str, list[dict]]:
    pack = get_pack(inp.pack_name)
    style_instruction = (
        "Стиль обращения — на «ты», непринуждённо, без формальностей."
        if inp.style == "ty"
        else "Стиль обращения — на «Вы», уважительно, без панибратства."
    )
    style_human = "на «ты»" if inp.style == "ty" else "на «Вы»"
    instruction = _GENERATION_INSTRUCTION.format(
        pack_name=pack.name,
        pack_description=pack.description,
        style_instruction=style_instruction,
        style_human=style_human,
    )
    user_content = (
        f"PROFILE.md:\n```\n{inp.profile_md}\n```\n\n"
        f"knowledge_base.json:\n```json\n{json.dumps(inp.kb_json, ensure_ascii=False, indent=2)}\n```"
    )
    messages = [{"role": "user", "content": user_content}]
    return instruction, messages


def _call_anthropic(
    *, system: str, messages: list[dict], model: str, api_key: str
) -> requests.Response:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    return requests.post(
        ANTHROPIC_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )


def generate_persona(inp: PersonaInput) -> PersonaBlocks:
    """Сгенерить 6 блоков через Claude. Fallback 4.6 → 4.5 при overload."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var not set")

    system, messages = _build_generation_messages(inp)

    # Primary attempt with quick retry on overload, then fallback model.
    resp = _call_anthropic(system=system, messages=messages, model=MODEL, api_key=api_key)
    if resp.status_code in (429, 503, 529):
        time.sleep(QUICK_RETRY_SLEEP)
        resp = _call_anthropic(system=system, messages=messages, model=MODEL, api_key=api_key)
    if resp.status_code in (429, 503, 529):
        resp = _call_anthropic(
            system=system, messages=messages, model=FALLBACK_MODEL, api_key=api_key
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Anthropic API call failed: {resp.status_code} {resp.text[:500]}"
        )

    body = resp.json()
    raw_text = body["content"][0]["text"].strip()
    # tolerate ```json wrapping if LLM ignored "no wrapping" instruction
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```", 2)[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    data = json.loads(raw_text)
    return PersonaBlocks(
        framing=data["framing"],
        chronic=data["chronic"],
        open_questions=data["open_questions"],
        therapy=data["therapy"],
        focus_areas=data["focus_areas"],
        typical_questions=data["typical_questions"],
    )


def render_prompt(
    inp: PersonaInput,
    blocks: PersonaBlocks,
    *,
    template_path: Path,
) -> str:
    """Подставить blocks + inp в markdown-шаблон через string.Template."""
    pack = get_pack(inp.pack_name)
    template = Template(template_path.read_text())
    style_text = (
        "- Обращение на «ты», непринуждённо, без формальностей.\n"
        "- Конкретно и по сути. Объяснять механизмы можно, но без перегруза.\n"
        "- Не пугать. Спокойный тон, фокус на «что предлагаю проверить»."
        if inp.style == "ty"
        else
        "- Обращение на «Вы», с уважением. Без панибратства.\n"
        "- Не пугать. Спокойно, с контекстом «вот что вижу, окончательно — за лечащим врачом».\n"
        "- Конкретно и по сути."
    )
    kb_sections = sorted(inp.kb_json.keys())
    return template.safe_substitute(
        name=inp.name,
        full_name=inp.full_name,
        age=inp.age,
        birth_date=inp.birth_date,
        location=inp.location,
        cohort=inp.cohort,
        cohort_relationship=inp.cohort_relationship,
        pack_name=pack.name,
        pack_description=pack.description,
        bio_line=inp.bio_line,
        communication_style=style_text,
        framing_block=blocks.framing,
        chronic_block=blocks.chronic,
        open_questions_block=blocks.open_questions,
        therapy_block=blocks.therapy,
        focus_areas_block=blocks.focus_areas,
        typical_questions_block=blocks.typical_questions,
        kb_sections_list=", ".join(kb_sections) if kb_sections else "(пусто)",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_persona_generator.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/onboard/persona_generator.py tests/test_onboard_persona_generator.py
git commit -m "onboard: persona generator — Claude-driven prompt assembly

Six structured blocks (framing/chronic/open_questions/therapy/focus_areas/
typical_questions) generated from KB+PROFILE via claude-sonnet-4-6 with quick
retry + 4.5 fallback on overload. render_prompt() splices blocks into the
family_active_coach.md template via string.Template.safe_substitute()."
```

---

## Task 6: Server deployer — `scripts/onboard/server_deployer.py`

**Files:**
- Create: `scripts/onboard/server_deployer.py`
- Create: `tests/test_onboard_server_deployer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_onboard_server_deployer.py
"""Server deployer — scp KB на Hetzner + psql UPDATE."""
import subprocess
from unittest.mock import patch, MagicMock, call

import pytest

from scripts.onboard.server_deployer import (
    ServerConfig,
    DeployResult,
    upload_kb,
    update_user_row,
    fetch_user_state,
    remove_kb,
)


@pytest.fixture
def cfg():
    return ServerConfig(
        host="116.203.213.137",
        user="root",
        password="testpw",
        deploy_path="/opt/healthvault",
        sshpass_path="/usr/bin/sshpass",
    )


def test_upload_kb_runs_atomic_scp(cfg, tmp_path):
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')
    runs: list[list[str]] = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)

    # Должно быть: 1) scp в .tmp 2) ssh mv .tmp → финальный путь
    assert any("scp" in " ".join(c) for c in runs)
    assert any("kb_999.json.tmp" in " ".join(c) for c in runs)
    assert any("mv " in " ".join(c) for c in runs)


def test_upload_kb_raises_on_scp_failure(cfg, tmp_path):
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="permission denied")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError) as exc:
            upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)
    assert "permission denied" in str(exc.value)


def test_update_user_row_builds_correct_sql(cfg):
    captured_sql = []

    def fake_run(cmd, **kw):
        captured_sql.append(" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="UPDATE 1\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        result = update_user_row(
            telegram_id=830908046,
            cohort="family",
            pack_name="respiratory_allergic",
            agent_system_prompt="hello",
            cfg=cfg,
        )

    joined = " ".join(captured_sql)
    assert "830908046" in joined
    assert "family" in joined
    assert "respiratory_allergic" in joined
    assert result.rows_affected == 1


def test_update_user_row_raises_when_zero_rows(cfg):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="UPDATE 0\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError) as exc:
            update_user_row(
                telegram_id=999999,
                cohort="family",
                pack_name="generic",
                agent_system_prompt="x",
                cfg=cfg,
            )
    assert "0 rows" in str(exc.value).lower() or "not found" in str(exc.value).lower()


def test_fetch_user_state_parses_psql_output(cfg):
    fake_output = (
        "830908046|external|generic|0|f\n"
    )

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=fake_output, stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        state = fetch_user_state(telegram_id=830908046, cfg=cfg)

    assert state.cohort == "external"
    assert state.pack_name == "generic"
    assert state.prompt_length == 0
    assert state.kb_on_server is False


def test_remove_kb_runs_ssh_rm(cfg):
    runs = []

    def fake_run(cmd, **kw):
        runs.append(" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        remove_kb(telegram_id=999, cfg=cfg)

    joined = " ".join(runs)
    assert "rm" in joined
    assert "kb_999.json" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_server_deployer.py -v`
Expected: ImportError

- [ ] **Step 3: Implement server_deployer.py**

```python
# scripts/onboard/server_deployer.py
"""Server deployer — scp KB + psql UPDATE с атомарностью и rollback."""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ServerConfig:
    host: str
    user: str
    password: str
    deploy_path: str
    sshpass_path: str = "/opt/homebrew/bin/sshpass"


@dataclass
class DeployResult:
    rows_affected: int


@dataclass
class UserServerState:
    telegram_id: int
    cohort: str
    pack_name: str
    prompt_length: int
    kb_on_server: bool


def _sshpass_args(cfg: ServerConfig) -> list[str]:
    return [cfg.sshpass_path, "-p", cfg.password]


def _ssh(cfg: ServerConfig, remote_cmd: str) -> subprocess.CompletedProcess:
    cmd = _sshpass_args(cfg) + [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        f"{cfg.user}@{cfg.host}",
        remote_cmd,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _scp(cfg: ServerConfig, local_path: Path, remote_path: str) -> subprocess.CompletedProcess:
    cmd = _sshpass_args(cfg) + [
        "scp",
        "-o", "StrictHostKeyChecking=no",
        str(local_path),
        f"{cfg.user}@{cfg.host}:{remote_path}",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _psql(cfg: ServerConfig, sql: str) -> subprocess.CompletedProcess:
    """Запустить psql -t -c <sql> через docker exec."""
    docker_cmd = (
        f"docker exec healthvault_postgres psql -U healthvault -d healthvault "
        f"-t -A -c {shlex.quote(sql)}"
    )
    return _ssh(cfg, docker_cmd)


def upload_kb(*, kb_path: Path, telegram_id: int, cfg: ServerConfig) -> None:
    """Залить kb_<tid>.json на сервер atomic'ом: scp в .tmp + mv."""
    tmp_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json.tmp"
    final_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json"

    scp = _scp(cfg, kb_path, tmp_remote)
    if scp.returncode != 0:
        raise RuntimeError(f"scp failed: {scp.stderr or scp.stdout}")

    mv = _ssh(cfg, f"mv {shlex.quote(tmp_remote)} {shlex.quote(final_remote)}")
    if mv.returncode != 0:
        # rollback .tmp
        _ssh(cfg, f"rm -f {shlex.quote(tmp_remote)}")
        raise RuntimeError(f"ssh mv failed: {mv.stderr or mv.stdout}")


def remove_kb(*, telegram_id: int, cfg: ServerConfig) -> None:
    """Удалить kb_<tid>.json с сервера (для rollback / --unenroll)."""
    final_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json"
    _ssh(cfg, f"rm -f {shlex.quote(final_remote)}")


def update_user_row(
    *,
    telegram_id: int,
    cohort: str,
    pack_name: str,
    agent_system_prompt: str,
    cfg: ServerConfig,
) -> DeployResult:
    """UPDATE users SET cohort, pack_name, agent_system_prompt WHERE telegram_id."""
    # Escape single quotes in prompt for SQL
    prompt_escaped = agent_system_prompt.replace("'", "''")
    sql = (
        f"UPDATE users SET cohort='{cohort}', pack_name='{pack_name}', "
        f"agent_system_prompt='{prompt_escaped}' "
        f"WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr or result.stdout}")

    out = result.stdout.strip()
    # Last non-empty line is "UPDATE N"
    last = [line for line in out.splitlines() if line.strip()][-1]
    rows = int(last.split()[-1]) if last.upper().startswith("UPDATE") else 0
    if rows == 0:
        raise RuntimeError(f"UPDATE matched 0 rows — user telegram_id={telegram_id} not found")
    return DeployResult(rows_affected=rows)


def fetch_user_state(*, telegram_id: int, cfg: ServerConfig) -> UserServerState:
    """SELECT текущего состояния юзера + проверка наличия kb-файла."""
    sql = (
        f"SELECT telegram_id, cohort, pack_name, "
        f"COALESCE(LENGTH(agent_system_prompt), 0), "
        f"EXISTS(SELECT 1 FROM pg_ls_dir('{cfg.deploy_path}') AS f "
        f"WHERE f='kb_{telegram_id}.json') "
        f"FROM users WHERE telegram_id={telegram_id};"
    )
    # NB: pg_ls_dir требует superuser — fallback: ssh ls check
    sql_simple = (
        f"SELECT telegram_id, cohort, pack_name, "
        f"COALESCE(LENGTH(agent_system_prompt), 0) "
        f"FROM users WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql_simple)
    if result.returncode != 0:
        raise RuntimeError(f"psql SELECT failed: {result.stderr or result.stdout}")
    line = result.stdout.strip().splitlines()[0]
    tid, cohort, pack, prompt_len = line.split("|")

    # Проверка файла на сервере через ssh ls
    check = _ssh(cfg, f"test -f {shlex.quote(cfg.deploy_path)}/kb_{telegram_id}.json && echo t || echo f")
    kb_on_server = check.stdout.strip() == "t"

    return UserServerState(
        telegram_id=int(tid),
        cohort=cohort,
        pack_name=pack,
        prompt_length=int(prompt_len),
        kb_on_server=kb_on_server,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_server_deployer.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/onboard/server_deployer.py tests/test_onboard_server_deployer.py
git commit -m "onboard: server deployer — atomic scp + psql UPDATE

scp lands in *.tmp then ssh mv (atomic). psql UPDATE via docker exec returns
rows_affected and raises on zero matches. fetch_user_state used for pre-flight
'is user already enrolled' check and post-flight verify."
```

---

## Task 7: Welcome sender — `scripts/onboard/welcome_sender.py`

**Files:**
- Create: `scripts/onboard/welcome_sender.py`
- Create: `tests/test_onboard_welcome_sender.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_onboard_welcome_sender.py
from unittest.mock import patch, MagicMock

import pytest

from scripts.onboard.welcome_sender import build_welcome_text, send_welcome


def test_build_welcome_text_ty_style():
    text = build_welcome_text(name="Игорь", style="ty", inviter_name="Александр")
    assert "Игорь" in text
    # На «ты» — должно быть «тебе» / «твоя»
    assert "тебе" in text.lower() or "твою" in text.lower() or "твои" in text.lower()
    assert "Александр" in text or "пап" in text.lower()
    # Должна быть подсказка как начать
    assert "витамин" in text.lower() or "анализ" in text.lower()


def test_build_welcome_text_vy_style():
    text = build_welcome_text(name="Валерия", style="vy", inviter_name="Александр")
    # На «Вы» — должно быть «Вам» / «Ваши»
    assert "Вам" in text or "Вашу" in text or "Ваши" in text


def test_send_welcome_calls_telegram_api(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    with patch("scripts.onboard.welcome_sender.requests.post", return_value=fake_response) as mock_post:
        msg_id = send_welcome(chat_id=999, text="hello")
    assert msg_id == 42
    args, kwargs = mock_post.call_args
    assert "test-token" in args[0]
    assert kwargs["json"]["chat_id"] == 999
    assert kwargs["json"]["text"] == "hello"


def test_send_welcome_raises_on_api_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    fake_response = MagicMock(status_code=400)
    fake_response.json.return_value = {"ok": False, "description": "chat not found"}

    with patch("scripts.onboard.welcome_sender.requests.post", return_value=fake_response):
        with pytest.raises(RuntimeError) as exc:
            send_welcome(chat_id=999, text="hello")
    assert "chat not found" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_welcome_sender.py -v`
Expected: ImportError

- [ ] **Step 3: Implement welcome_sender.py**

```python
# scripts/onboard/welcome_sender.py
"""Welcome-сообщение новому family-юзеру через Telegram Bot API."""
from __future__ import annotations

import os
from typing import Literal

import requests


def build_welcome_text(
    *,
    name: str,
    style: Literal["ty", "vy"],
    inviter_name: str,
) -> str:
    """Текст welcome'а — короткий, тёплый, с privacy-блоком и подсказкой."""
    if style == "ty":
        return (
            f"Привет, {name}!\n\n"
            f"{inviter_name} (твой папа) подключил мне твою историю анализов и "
            f"медицинских записей. Теперь я знаю про твой витамин D, аллергии, "
            f"прививки и могу отвечать на вопросы про здоровье, а не только "
            f"логировать еду.\n\n"
            f"📦 Где данные: на сервере проекта Botkin в Германии (Hetzner). "
            f"Доступ только у тебя через @Botkin_md_bot. Папа видит общие "
            f"сводки по семье, но не твою личную переписку со мной.\n\n"
            f"Хочешь отключить расширенный режим — напиши папе или мне «удали мои "
            f"данные».\n\n"
            f"Попробуй спросить:\n"
            f"• «какой у меня был последний витамин D?»\n"
            f"• «на что у меня аллергия?»\n"
            f"• «когда последняя прививка от клещевого энцефалита?»"
        )
    return (
        f"Здравствуйте, {name}!\n\n"
        f"{inviter_name} подключил мне Вашу историю анализов и медицинских записей. "
        f"Теперь я могу отвечать на вопросы про Ваше здоровье, а не только "
        f"логировать питание.\n\n"
        f"📦 Где данные: на сервере проекта Botkin в Германии. Доступ только у Вас "
        f"через @Botkin_md_bot. {inviter_name} видит общие сводки по семье, но "
        f"не Вашу личную переписку со мной.\n\n"
        f"Хотите отключить расширенный режим — напишите «удали мои данные».\n\n"
        f"Попробуйте спросить:\n"
        f"• «какой у меня последний витамин D?»\n"
        f"• «покажи мои хронические диагнозы»"
    )


def send_welcome(*, chat_id: int, text: str) -> int:
    """Отправить через Bot API. Вернуть message_id."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var not set")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    body = resp.json()
    if resp.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body.get('description', resp.text)}")
    return body["result"]["message_id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_welcome_sender.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/onboard/welcome_sender.py tests/test_onboard_welcome_sender.py
git commit -m "onboard: welcome sender — Telegram Bot API + bilingual style

build_welcome_text branches on 'ty'/'vy'. send_welcome wraps sendMessage,
returns message_id. Hardcoded privacy block + 3 example questions."
```

---

## Task 8: CLI orchestrator — `scripts/onboard_family_user.py`

**Files:**
- Create: `scripts/onboard_family_user.py`
- Create: `tests/test_onboard_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_onboard_cli.py
"""CLI integration tests for onboard_family_user.py — все компоненты замоканы."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "onboard_family_user.py"


def _run_cli(*args, env=None):
    """Запустить CLI как subprocess. Возвращает CompletedProcess."""
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))


def test_cli_help_works():
    """`--help` не падает и упоминает основные команды."""
    result = _run_cli("--help")
    assert result.returncode == 0
    out = result.stdout
    assert "--enroll" in out
    assert "--refresh-kb" in out
    assert "--refresh-prompt" in out
    assert "--unenroll" in out
    assert "--dry-run" in out


def test_cli_enroll_requires_tid():
    """--enroll без --tid должно падать."""
    result = _run_cli("--enroll")
    assert result.returncode != 0


def test_cli_dry_run_does_not_modify(tmp_path, monkeypatch):
    """--dry-run печатает план, но не дёргает ни scp, ни psql, ни Telegram."""
    # Эту проверку проще написать unit-style — импортировать main() и проверить
    # что mocks не были вызваны. См. test_cli_dry_run_unit ниже.


def test_cli_dry_run_unit(monkeypatch, tmp_path):
    """Импортированный CLI в --dry-run не дёргает деструктивные операции."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SERVER_PASSWORD", "dummy")

    # Подготовить fake FamilyHealth
    fam = tmp_path / "FamilyHealth" / "Test User"
    fam.mkdir(parents=True)
    (fam / "knowledge_base.json").write_text(json.dumps({
        "blood_tests": [{"date": "2025-01-01", "values": {"vitamin_d": 30}}],
        "diagnoses": ["J45"],
    }))
    (fam / "PROFILE.md").write_text("Test profile")

    sys.path.insert(0, str(REPO_ROOT))
    from scripts import onboard_family_user as cli

    with patch.object(cli.server_deployer, "upload_kb") as m_upload, \
         patch.object(cli.server_deployer, "update_user_row") as m_update, \
         patch.object(cli.welcome_sender, "send_welcome") as m_welcome, \
         patch.object(cli.persona_generator, "generate_persona") as m_persona, \
         patch.object(cli.server_deployer, "fetch_user_state") as m_fetch:
        m_fetch.return_value = cli.server_deployer.UserServerState(
            telegram_id=999, cohort="external", pack_name="generic",
            prompt_length=0, kb_on_server=False,
        )
        m_persona.return_value = cli.persona_generator.PersonaBlocks(
            framing="x", chronic="x", open_questions="x",
            therapy="x", focus_areas="x", typical_questions="x",
        )
        rc = cli.main([
            "--enroll",
            "--tid", "999",
            "--family-folder", str(fam),
            "--name", "Test",
            "--full-name", "Test User",
            "--age", "30",
            "--birth-date", "1995-01-01",
            "--location", "Test City",
            "--cohort", "family",
            "--cohort-relationship", "test",
            "--bio-line", "test bio",
            "--pack", "generic",
            "--style", "ty",
            "--dry-run",
            "--yes",
            "--prompt-output", str(tmp_path / "test.md"),
        ])
    assert rc == 0
    m_upload.assert_not_called()
    m_update.assert_not_called()
    m_welcome.assert_not_called()


def test_cli_enroll_full_flow(monkeypatch, tmp_path):
    """--enroll без --dry-run дёргает upload_kb, update_user_row, (с --send-welcome) send_welcome."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SERVER_PASSWORD", "dummy")

    fam = tmp_path / "FamilyHealth" / "Test User"
    fam.mkdir(parents=True)
    (fam / "knowledge_base.json").write_text(json.dumps({
        "blood_tests": [{"date": "2025-01-01", "values": {"vitamin_d": 30}}],
        "diagnoses": ["J45"],
    }))
    (fam / "PROFILE.md").write_text("Test profile")

    sys.path.insert(0, str(REPO_ROOT))
    from scripts import onboard_family_user as cli

    with patch.object(cli.server_deployer, "upload_kb") as m_upload, \
         patch.object(cli.server_deployer, "update_user_row",
                      return_value=cli.server_deployer.DeployResult(rows_affected=1)) as m_update, \
         patch.object(cli.welcome_sender, "send_welcome", return_value=123) as m_welcome, \
         patch.object(cli.persona_generator, "generate_persona") as m_persona, \
         patch.object(cli.server_deployer, "fetch_user_state") as m_fetch, \
         patch.object(cli, "_git_commit_artifact"):
        m_fetch.side_effect = [
            cli.server_deployer.UserServerState(999, "external", "generic", 0, False),
            cli.server_deployer.UserServerState(999, "family", "generic", 5000, True),
        ]
        m_persona.return_value = cli.persona_generator.PersonaBlocks(
            framing="x", chronic="x", open_questions="x",
            therapy="x", focus_areas="x", typical_questions="x",
        )
        rc = cli.main([
            "--enroll",
            "--tid", "999",
            "--family-folder", str(fam),
            "--name", "Test",
            "--full-name", "Test User",
            "--age", "30",
            "--birth-date", "1995-01-01",
            "--location", "Test City",
            "--cohort", "family",
            "--cohort-relationship", "test",
            "--bio-line", "test bio",
            "--pack", "generic",
            "--style", "ty",
            "--send-welcome",
            "--yes",
            "--no-commit",
            "--prompt-output", str(tmp_path / "test.md"),
        ])
    assert rc == 0
    m_upload.assert_called_once()
    m_update.assert_called_once()
    m_welcome.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_onboard_cli.py -v`
Expected: ImportError or "no such file"

- [ ] **Step 3: Implement onboard_family_user.py**

```python
#!/usr/bin/env python3
"""onboard_family_user.py — CLI оркестратор подключения семейного юзера к BotkinClaw.

Examples:
  # Полный onboarding Игоря (без отправки welcome пока):
  python3 scripts/onboard_family_user.py --enroll \\
      --tid 830908046 \\
      --family-folder "$HOME/Library/CloudStorage/.../FamilyHealth/Игорь Лысковский — Здоровье" \\
      --name "Игорь" --full-name "Лысковский Игорь Александрович" \\
      --age "21 год" --birth-date "2004-08-15" --location "Москва" \\
      --cohort family --cohort-relationship "сын Александра" \\
      --bio-line "Студент. Аллергия на пыль, поллиноз." \\
      --pack respiratory_allergic --style ty \\
      --dry-run

  # После ревью — реальный запуск + welcome:
  python3 scripts/onboard_family_user.py --enroll ... --send-welcome --yes

  # Только обновить промпт (LLM-вызов):
  python3 scripts/onboard_family_user.py --refresh-prompt --tid 830908046

  # Применить вручную отредактированный промпт:
  python3 scripts/onboard_family_user.py --refresh-prompt --tid 830908046 \\
      --from-file scripts/server/agent_prompts/igor.md

  # Отозвать (rollback):
  python3 scripts/onboard_family_user.py --unenroll --tid 830908046

См. design: docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md
См. runbook: docs/operations/onboard-family-user.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Make package imports work whether invoked as script or module
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.onboard import (
    kb_validator,
    persona_generator,
    server_deployer,
    snapshot,
    welcome_sender,
)
from core.packs import get_pack

TEMPLATE_PATH = REPO_ROOT / "scripts" / "server" / "agent_prompts" / "templates" / "family_active_coach.md"
PROMPT_DIR = REPO_ROOT / "scripts" / "server" / "agent_prompts"


def _server_config() -> server_deployer.ServerConfig:
    """Загрузить из env (или дефолтов проекта)."""
    return server_deployer.ServerConfig(
        host=os.environ.get("SERVER_HOST", "116.203.213.137"),
        user=os.environ.get("SERVER_USER", "root"),
        password=os.environ["SERVER_PASSWORD"],
        deploy_path=os.environ.get("SERVER_DEPLOY_PATH", "/opt/healthvault"),
        sshpass_path=os.environ.get("SSHPASS_PATH", "/opt/homebrew/bin/sshpass"),
    )


def _git_commit_artifact(prompt_path: Path, telegram_id: int, pack_name: str) -> None:
    msg = f"agent: onboard telegram_id={telegram_id} — {pack_name}"
    subprocess.run(["git", "add", str(prompt_path), "core/packs.py"], check=False, cwd=REPO_ROOT)
    subprocess.run(["git", "commit", "-m", msg], check=False, cwd=REPO_ROOT)


def _confirm(message: str, *, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    print(message)
    return input("Продолжить? [y/N] ").strip().lower() == "y"


def _short_name_from_full(name: str) -> str:
    """`Игорь` → `igor`. Простая транслитерация для имени файла."""
    table = str.maketrans(
        "абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
        "abvgdejziyklmnoprstufhccss_y_eyaABVGDEJZIYKLMNOPRSTUFHCCSS_Y_EYA",
    )
    return name.translate(table).lower().replace(" ", "_")


def cmd_enroll(args) -> int:
    """Полный onboarding."""
    fam_folder = Path(args.family_folder)
    kb_path = fam_folder / "knowledge_base.json"
    profile_path = fam_folder / "PROFILE.md"

    # 1. Pre-flight
    print(f"== Pre-flight checks ==")
    kb_summary = kb_validator.validate_kb(kb_path)
    print(f"  KB ok: {kb_summary.blood_tests_count} blood_tests, {kb_summary.size_bytes} bytes")
    pack = get_pack(args.pack)
    print(f"  Pack ok: {pack.name} — {pack.description}")

    cfg = _server_config()
    state_before = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(f"  Current server state: cohort={state_before.cohort}, "
          f"pack={state_before.pack_name}, prompt_len={state_before.prompt_length}, "
          f"kb_on_server={state_before.kb_on_server}")
    already_enrolled = state_before.prompt_length > 0 and state_before.kb_on_server
    if already_enrolled and not args.force:
        print(f"❌ User {args.tid} уже enrolled. Используй --force для перезаписи "
              f"или --refresh-prompt / --refresh-kb для частичного обновления.")
        return 1

    snap = snapshot.UserSnapshot(
        telegram_id=args.tid,
        cohort=state_before.cohort,
        pack_name=state_before.pack_name,
        agent_system_prompt="",  # не вытягиваем полный текст, для rollback не нужен — снимем отдельно
        kb_existed_on_server=state_before.kb_on_server,
    )
    snapshot_path = snapshot.save_snapshot(snap)
    print(f"  Snapshot saved: {snapshot_path}")

    # 2. Validate again (size + structure already done) — skip

    # 3. LLM persona generation
    print(f"== Generating persona via Claude ==")
    profile_md = profile_path.read_text() if profile_path.exists() else ""
    kb_data = json.loads(kb_path.read_text())
    inp = persona_generator.PersonaInput(
        name=args.name,
        full_name=args.full_name,
        age=args.age,
        birth_date=args.birth_date,
        location=args.location,
        cohort=args.cohort,
        cohort_relationship=args.cohort_relationship,
        pack_name=args.pack,
        bio_line=args.bio_line,
        kb_json=kb_data,
        profile_md=profile_md,
        style=args.style,
    )
    if args.from_file:
        print(f"  Using prompt from file: {args.from_file} (skipping LLM call)")
        prompt_text = Path(args.from_file).read_text()
    else:
        blocks = persona_generator.generate_persona(inp)
        prompt_text = persona_generator.render_prompt(inp, blocks, template_path=TEMPLATE_PATH)

    # Save artifact
    if args.prompt_output:
        prompt_path = Path(args.prompt_output)
    else:
        prompt_path = PROMPT_DIR / f"{_short_name_from_full(args.name)}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text)
    print(f"  Prompt artifact saved: {prompt_path} ({len(prompt_text)} chars)")

    # 4. Confirmation
    print(f"\n== Plan ==")
    print(f"  KB: scp {kb_path} → {cfg.deploy_path}/kb_{args.tid}.json")
    print(f"  DB: UPDATE users SET cohort='{args.cohort}', pack_name='{args.pack}', "
          f"agent_system_prompt=<{len(prompt_text)} chars> WHERE telegram_id={args.tid}")
    if args.send_welcome:
        print(f"  Welcome: Bot API sendMessage chat_id={args.tid}")
    print(f"  Prompt preview (first 500 chars):\n---\n{prompt_text[:500]}\n---")

    if args.dry_run:
        print(f"\n💡 --dry-run: ничего не применяется. Запусти без --dry-run для реального onboarding'а.")
        return 0
    if not _confirm("\nПрименить изменения?", auto_yes=args.yes):
        print("Отменено пользователем.")
        return 1

    # 5. Apply
    print(f"\n== Applying ==")
    try:
        server_deployer.upload_kb(kb_path=kb_path, telegram_id=args.tid, cfg=cfg)
        print(f"  ✓ KB uploaded")
    except Exception as e:
        print(f"❌ KB upload failed: {e}")
        return 2

    try:
        result = server_deployer.update_user_row(
            telegram_id=args.tid,
            cohort=args.cohort,
            pack_name=args.pack,
            agent_system_prompt=prompt_text,
            cfg=cfg,
        )
        print(f"  ✓ DB updated ({result.rows_affected} row)")
    except Exception as e:
        print(f"❌ DB update failed: {e}")
        print(f"  Rollback: removing KB from server")
        server_deployer.remove_kb(telegram_id=args.tid, cfg=cfg)
        return 3

    # 6. Verify
    print(f"\n== Post-flight verify ==")
    state_after = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(f"  cohort={state_after.cohort}, pack={state_after.pack_name}, "
          f"prompt_len={state_after.prompt_length}, kb_on_server={state_after.kb_on_server}")
    assert state_after.cohort == args.cohort
    assert state_after.pack_name == args.pack
    assert state_after.prompt_length >= len(prompt_text) - 10  # small encoding drift OK
    assert state_after.kb_on_server is True
    print(f"  ✓ Verified")

    # 7. Welcome (optional)
    if args.send_welcome:
        text = welcome_sender.build_welcome_text(
            name=args.name, style=args.style, inviter_name="Александр",
        )
        msg_id = welcome_sender.send_welcome(chat_id=args.tid, text=text)
        print(f"  ✓ Welcome sent (message_id={msg_id})")

    # 8. Git commit
    if not args.no_commit:
        _git_commit_artifact(prompt_path, args.tid, args.pack)
        print(f"  ✓ Git commit created locally (запушь когда готов)")
    else:
        print(f"  ⚠ --no-commit: артефакт {prompt_path} НЕ закоммичен")

    print(f"\n✅ Onboarding {args.name} (telegram_id={args.tid}) завершён.")
    return 0


def cmd_unenroll(args) -> int:
    """Отозвать enrollment: rm KB, cohort→external, prompt→''."""
    cfg = _server_config()
    state_before = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(f"Current: cohort={state_before.cohort}, pack={state_before.pack_name}, "
          f"prompt_len={state_before.prompt_length}, kb_on_server={state_before.kb_on_server}")

    if args.dry_run:
        print(f"💡 --dry-run: ничего не применяется.")
        return 0
    if not _confirm(f"Отозвать enrollment у telegram_id={args.tid}?", auto_yes=args.yes):
        return 1

    server_deployer.update_user_row(
        telegram_id=args.tid,
        cohort="external",
        pack_name="generic",
        agent_system_prompt="",
        cfg=cfg,
    )
    server_deployer.remove_kb(telegram_id=args.tid, cfg=cfg)
    print(f"✅ Unenrolled telegram_id={args.tid}")
    return 0


def cmd_refresh_kb(args) -> int:
    """Только перезалить KB на сервере (без LLM, без UPDATE остальных полей)."""
    fam_folder = Path(args.family_folder) if args.family_folder else None
    if not fam_folder:
        print("❌ --family-folder обязателен для --refresh-kb")
        return 1
    kb_path = fam_folder / "knowledge_base.json"
    kb_validator.validate_kb(kb_path)
    cfg = _server_config()
    if args.dry_run:
        print(f"💡 --dry-run: scp {kb_path} → {cfg.deploy_path}/kb_{args.tid}.json")
        return 0
    server_deployer.upload_kb(kb_path=kb_path, telegram_id=args.tid, cfg=cfg)
    print(f"✅ KB refreshed for telegram_id={args.tid}")
    return 0


def cmd_refresh_prompt(args) -> int:
    """Только пересоздать prompt (LLM-вызов или --from-file)."""
    cfg = _server_config()
    if args.from_file:
        prompt_text = Path(args.from_file).read_text()
        print(f"Using prompt from {args.from_file} ({len(prompt_text)} chars)")
    else:
        # Требуем тех же входов что и --enroll
        fam_folder = Path(args.family_folder)
        kb_data = json.loads((fam_folder / "knowledge_base.json").read_text())
        profile_md = (fam_folder / "PROFILE.md").read_text() if (fam_folder / "PROFILE.md").exists() else ""
        inp = persona_generator.PersonaInput(
            name=args.name, full_name=args.full_name, age=args.age,
            birth_date=args.birth_date, location=args.location,
            cohort=args.cohort, cohort_relationship=args.cohort_relationship,
            pack_name=args.pack, bio_line=args.bio_line,
            kb_json=kb_data, profile_md=profile_md, style=args.style,
        )
        blocks = persona_generator.generate_persona(inp)
        prompt_text = persona_generator.render_prompt(inp, blocks, template_path=TEMPLATE_PATH)

    if args.dry_run:
        print(f"💡 --dry-run: будет UPDATE prompt_len={len(prompt_text)} for tid={args.tid}")
        return 0

    state = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    server_deployer.update_user_row(
        telegram_id=args.tid,
        cohort=state.cohort,
        pack_name=state.pack_name,
        agent_system_prompt=prompt_text,
        cfg=cfg,
    )
    print(f"✅ Prompt refreshed for telegram_id={args.tid}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Onboard a family user to BotkinClaw (KB + prompt + welcome).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    cmd = p.add_mutually_exclusive_group(required=True)
    cmd.add_argument("--enroll", action="store_true")
    cmd.add_argument("--unenroll", action="store_true")
    cmd.add_argument("--refresh-kb", action="store_true", dest="refresh_kb")
    cmd.add_argument("--refresh-prompt", action="store_true", dest="refresh_prompt")

    p.add_argument("--tid", type=int, required=True, help="Telegram ID of the user")
    p.add_argument("--family-folder", help="Path to FamilyHealth/<name> folder")
    p.add_argument("--name", help="Short name, e.g. 'Игорь'")
    p.add_argument("--full-name", help="Full name")
    p.add_argument("--age", help="Age as words, e.g. '21 год'")
    p.add_argument("--birth-date", help="YYYY-MM-DD")
    p.add_argument("--location", help="City")
    p.add_argument("--cohort", choices=["owner", "family", "early_user", "external"])
    p.add_argument("--cohort-relationship", help="e.g. 'сын Александра'")
    p.add_argument("--bio-line", help="One-line bio")
    p.add_argument("--pack", help="Pack name (from core/packs.py)")
    p.add_argument("--style", choices=["ty", "vy"], default="ty")
    p.add_argument("--from-file", help="Use prompt from file instead of generating (for --refresh-prompt)")
    p.add_argument("--prompt-output", help="Override where to save prompt artifact")

    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Overwrite existing enrollment")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    p.add_argument("--send-welcome", action="store_true")
    p.add_argument("--no-commit", action="store_true", help="Don't git commit the prompt artifact")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.enroll:
        return cmd_enroll(args)
    if args.unenroll:
        return cmd_unenroll(args)
    if args.refresh_kb:
        return cmd_refresh_kb(args)
    if args.refresh_prompt:
        return cmd_refresh_prompt(args)
    parser.error("No command specified")
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_onboard_cli.py -v`
Expected: 4 passed (test_cli_help_works, test_cli_enroll_requires_tid, test_cli_dry_run_unit, test_cli_enroll_full_flow)

- [ ] **Step 5: Run the whole test suite to verify nothing else broke**

Run: `python3 -m pytest tests/ -v -k "onboard or packs" 2>&1 | tail -30`
Expected: all green for our new tests

- [ ] **Step 6: Commit**

```bash
git add scripts/onboard_family_user.py tests/test_onboard_cli.py
git commit -m "onboard: CLI orchestrator scripts/onboard_family_user.py

Argparse-based CLI with --enroll/--unenroll/--refresh-kb/--refresh-prompt
commands plus --dry-run/--force/--yes/--from-file/--send-welcome/--no-commit
modifiers. Orchestrates kb_validator → persona_generator → server_deployer →
welcome_sender with snapshot+rollback on failure."
```

---

## Task 9: Runbook + AI_CHANGELOG

**Files:**
- Create: `docs/operations/onboard-family-user.md`
- Modify: `docs/ai_context/AI_CHANGELOG.md`

- [ ] **Step 1: Write the runbook**

Write to `docs/operations/onboard-family-user.md`:

````markdown
# Подключение семейного юзера к BotkinClaw

Runbook для будущих onboarding'ов через `scripts/onboard_family_user.py`.

## Когда применять

- Юзер уже подключён к боту (есть строка в `users` с telegram_id).
- В `~/.../FamilyHealth/<name>/` лежит распарсенный `knowledge_base.json`.
- Хочется, чтобы юзер мог общаться с агентом не только про еду.

Если KB ещё не распарсен — сначала прогнать `scripts/import/parse_lab_pdfs.py`.

## Pre-flight

1. **Проверить что юзер есть в БД:**
   ```bash
   /opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
       "docker exec healthvault_postgres psql -U healthvault -d healthvault \
        -c \"SELECT telegram_id, first_name, cohort FROM users WHERE telegram_id=<TID>;\""
   ```
2. **Проверить KB:**
   ```bash
   python3 -c "import json; kb=json.load(open('FamilyHealth/.../knowledge_base.json'));
   print(list(kb.keys()), 'blood_tests:', len(kb.get('blood_tests',[])))"
   ```
3. **Доступные packs** — см. `core/packs.py`. Сейчас:
   - `generic` — без специфического фокуса
   - `bariatric` — снижение веса + метаболика
   - `cardiac` — кардиометаболический риск
   - `respiratory_allergic` — астма + аллерго-история + регулярный скрининг

## Шаг 1. Dry-run

Собрать команду и прогнать с `--dry-run`:

```bash
python3 scripts/onboard_family_user.py --enroll \
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
- KB summary совпадает с ожиданием
- Pack корректный
- Превью промпта читается, не выглядит как машинный мусор
- Текущее состояние юзера на сервере как ожидалось

## Шаг 2. Реальный enroll

Тот же команд без `--dry-run`, плюс `--send-welcome` если готов отправить welcome:

```bash
python3 scripts/onboard_family_user.py --enroll ... --send-welcome
```

Без `--yes` скрипт спросит подтверждение. С `--yes` сразу применит.

## Шаг 3. E2E verify

```python
# В корне проекта, локально (нужен Postgres-доступ через .env):
python3 -c "
from core.agent_chat import ask_agent
print(ask_agent(<TID>, 'какой у меня был последний витамин D?'))
"
```

Ожидаем ответ с реальным значением и датой из KB.

## Откат / частичное обновление

| Что нужно | Команда |
|---|---|
| Перезалить KB после обновления локального | `--refresh-kb --tid X --family-folder ...` |
| Пересоздать промпт через Claude | `--refresh-prompt --tid X --family-folder ... --name ... --pack ...` |
| Применить ручную правку промпта | `--refresh-prompt --tid X --from-file scripts/server/agent_prompts/<name>.md` |
| Полностью отозвать enrollment | `--unenroll --tid X` |

## Troubleshooting

- **Anthropic 529 на 4.6** — скрипт сам делает quick retry и fallback на 4.5. Если оба упали — повторить через 1-2 минуты или использовать `--from-file` со старым артефактом промпта.
- **scp прерван** — `--enroll` сам откатит KB-файл при ошибке DB UPDATE. Если scp упал — ничего не было применено, можно перезапустить.
- **psql: 0 rows updated** — юзер не существует в `users`. Проверь telegram_id.
- **Welcome не дошёл** — `chat_id` должен совпадать с telegram_id юзера, юзер должен был хотя бы раз написать боту (chat существует).

## Документы

- Дизайн: [docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md](../superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md)
- Pack registry: [core/packs.py](../../core/packs.py)
- Шаблон промпта: [scripts/server/agent_prompts/templates/family_active_coach.md](../../scripts/server/agent_prompts/templates/family_active_coach.md)
````

- [ ] **Step 2: Append to AI_CHANGELOG.md**

Read first to find insertion point:

```bash
head -20 docs/ai_context/AI_CHANGELOG.md
```

Then insert at top of changes list (after header):

```markdown
## 2026-05-22

- **Igor onboarding to BotkinClaw + reusable family-user pipeline.** Подключён Игорь (telegram_id 830908046) как family/respiratory_allergic. Создан `scripts/onboard_family_user.py` с командами enroll/refresh-kb/refresh-prompt/unenroll, поддержкой dry-run и автоматическим rollback. Реестр packs вынесен в `core/packs.py` как декларативный `@dataclass(frozen=True)`. Шаблон промпта `scripts/server/agent_prompts/templates/family_active_coach.md` с `string.Template`-плейсхолдерами. Дизайн: [docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md](docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md), runbook: [docs/operations/onboard-family-user.md](docs/operations/onboard-family-user.md). Следующее применение — подключение мамы (Валерия Лысковская) тем же скриптом.
```

- [ ] **Step 3: Commit**

```bash
git add docs/operations/onboard-family-user.md docs/ai_context/AI_CHANGELOG.md
git commit -m "docs: runbook for family-user onboarding + AI_CHANGELOG entry"
```

---

## Task 10: Regression smoke — verify existing users aren't affected

**Цель:** Убедиться что Pavel и Andrey продолжают работать после изменений в коде.
Никакие файлы не создаём — только проверка.

- [ ] **Step 1: Verify Pavel's prompt is intact on server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"SELECT telegram_id, cohort, pack_name, LENGTH(agent_system_prompt) \
          FROM users WHERE telegram_id IN (33831673, 836757955);\""
```

Expected:
```
 telegram_id |  cohort   | pack_name | length
-------------+-----------+-----------+--------
    33831673 | family    | generic   |  10873
   836757955 | early_user| cardiac   |  10362
```

(числа могут отличаться на пару байт — главное оба >10000)

- [ ] **Step 2: Verify Pavel's KB still on server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "ls -la /opt/healthvault/kb_*.json"
```

Expected: `kb_33831673.json` и `kb_836757955.json` присутствуют, размер ≈ как раньше.

- [ ] **Step 3: E2E smoke — Pavel still responds**

```python
python3 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(33831673, 'привет, как у меня дела по последним анализам?'))
"
```

Expected: ответ упоминает Павла, его данные, использует tools. Если ответ пустой / падает / не упоминает контекст Павла — STOP, ничего больше не деплоить, расследовать.

- [ ] **Step 4: E2E smoke — Andrey still responds**

```python
python3 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(836757955, 'покажи мою последнюю динамику давления'))
"
```

Expected: Andrey'ев ответ с его BP-данными.

- [ ] **Step 5: Notice and stop on regression**

Если шаг 3 или 4 упали — **остановиться**, **не запускать Task 11**, открыть отдельный investigation. Скорее всего что-то в `core/agent_chat.py` сломалось от изменений в `core/packs.py` (хотя ничего не должно — packs.py никто не импортирует на серверной стороне).

---

## Task 11: Build Igor's KB & PROFILE inputs

**Цель:** Подготовить параметры для CLI-запуска. Это **исследование**, без коммитов.

- [ ] **Step 1: Read Igor's PROFILE.md**

```bash
cat "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Игорь Лысковский — Здоровье/PROFILE.md" | head -50
```

- [ ] **Step 2: Survey KB structure**

```bash
python3 -c "
import json
kb = json.load(open('/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Игорь Лысковский — Здоровье/knowledge_base.json'))
print('Sections:', sorted(kb.keys()))
print('blood_tests count:', len(kb.get('blood_tests', [])))
print('diagnoses:', kb.get('diagnoses', []))
print('vitamin_d history points:', len(kb.get('vitamin_d', [])))
print('allergy_tests count:', len(kb.get('allergy_tests', [])))
"
```

- [ ] **Step 3: Compose the CLI args**

Записать (для использования в Task 12) команду:

```
--enroll --tid 830908046 \
--family-folder "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Игорь Лысковский — Здоровье" \
--name "Игорь" \
--full-name "Лысковский Игорь Александрович" \
--age "21 год" \
--birth-date "2004-08-15" \    <- свериться с PROFILE.md
--location "Москва" \           <- свериться с PROFILE.md
--cohort family \
--cohort-relationship "младший сын Александра" \
--bio-line "Студент. Аллергия (пыль/поллиноз) с детства, бронхиальная астма J45, регулярный скрининг КЭ-вакцинации." \   <- адаптировать под PROFILE.md
--pack respiratory_allergic \
--style ty
```

Если в PROFILE.md дата рождения, локация или диагнозы расходятся — использовать те, что в PROFILE.md (они источник истины).

---

## Task 12: Run dry-run for Igor

- [ ] **Step 1: Load env**

```bash
cd "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin"
set -a
source .env
set +a
export SERVER_PASSWORD="SERVER_PASSWORD_REDACTED"  # see scripts/fetch_remote_nutrition.sh
```

- [ ] **Step 2: Run with --dry-run**

```bash
python3 scripts/onboard_family_user.py --enroll \
    --tid 830908046 \
    --family-folder "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Игорь Лысковский — Здоровье" \
    --name "Игорь" \
    --full-name "<из PROFILE.md>" \
    --age "<из PROFILE.md>" \
    --birth-date "<из PROFILE.md>" \
    --location "<из PROFILE.md>" \
    --cohort family \
    --cohort-relationship "младший сын Александра" \
    --bio-line "<из PROFILE.md>" \
    --pack respiratory_allergic \
    --style ty \
    --dry-run
```

Expected output:
- Pre-flight: KB ok, Pack ok, current state external/generic/0/false
- Snapshot saved
- Persona generation: ~30 sec, prompt artifact saved
- Plan printed
- `💡 --dry-run: ничего не применяется`

- [ ] **Step 3: Review generated prompt artifact**

Открыть `scripts/server/agent_prompts/igor.md` (или куда сохранился) и прочитать целиком. Проверить:
- Стиль обращения на «ты»
- Все факты (диагнозы, аллергии) совпадают с KB
- Pack `respiratory_allergic` упомянут
- Имя/возраст корректные
- Никакой выдумки (особенно про лечащих врачей, операции, лекарства)

- [ ] **Step 4: Если есть правки — править вручную в файле**

И затем в Task 13 использовать `--from-file scripts/server/agent_prompts/igor.md`.

---

## Task 13: Real enroll for Igor (без welcome пока)

- [ ] **Step 1: Run enrollment**

```bash
python3 scripts/onboard_family_user.py --enroll \
    --tid 830908046 \
    --family-folder "..." \
    [все те же args что в Task 12] \
    --from-file scripts/server/agent_prompts/igor.md \
    --yes
    # NO --send-welcome yet — отправим в Task 15 после E2E verify
```

Expected:
- `✓ KB uploaded`
- `✓ DB updated (1 row)`
- `✓ Verified`
- Git commit создан локально

- [ ] **Step 2: Confirm DB state**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"SELECT telegram_id, cohort, pack_name, LENGTH(agent_system_prompt) \
          FROM users WHERE telegram_id=830908046;\""
```

Expected: `830908046 | family | respiratory_allergic | ~8000+`

- [ ] **Step 3: Confirm KB on server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "ls -la /opt/healthvault/kb_830908046.json"
```

Expected: file exists, size ≈ 52 KB.

---

## Task 14: E2E verify for Igor

- [ ] **Step 1: Ask agent a question that requires KB**

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(830908046, 'какой у меня был последний витамин D и когда сдавал?'))
"
```

Expected: ответ упоминает конкретное число (например 35 нг/мл) и конкретную дату (например 08.05.2025) из KB.

- [ ] **Step 2: Ask about allergies**

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(830908046, 'на что у меня аллергия?'))
"
```

Expected: упоминает конкретные аллергены из `allergy_tests` секции KB.

- [ ] **Step 3: Ask about non-existent data (graceful failure)**

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from core.agent_chat import ask_agent
print(ask_agent(830908046, 'какое у меня было давление вчера?'))
"
```

Expected: вежливый ответ что АД-замеров пока нет в системе, предложение начать логировать.

- [ ] **Step 4: Verify food logging still works (regression for Igor)**

Это не нужно дёргать через ask_agent — питание идёт через router_food. Достаточно убедиться через БД что новых поломок нет:

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"SELECT count(*) FROM nutrition_log WHERE user_id=830908046;\""
```

Expected: 2 (как было до начала, или больше если Игорь логировал ещё).

- [ ] **Step 5: Stop if any step fails**

Если шаг 1 или 2 не дают данные из KB — **stop**, **не отправлять welcome**, расследовать. Проверить:
- prompt действительно записался (его длина >0 в БД)
- KB-файл на сервере читается (`docker exec healthvault_bot test -r /opt/healthvault/kb_830908046.json`)
- agent_chat действительно дёргает `get_kb_value` или `get_recent_biomarkers` в логах

---

## Task 15: Send welcome to Igor

- [ ] **Step 1: Preview welcome text locally**

```bash
python3 -c "
from scripts.onboard.welcome_sender import build_welcome_text
print(build_welcome_text(name='Игорь', style='ty', inviter_name='Александр'))
"
```

Прочитать целиком, проверить что текст звучит органично и privacy-блок понятен.

- [ ] **Step 2: Send via CLI**

```bash
python3 scripts/onboard_family_user.py --refresh-prompt \
    --tid 830908046 \
    --from-file scripts/server/agent_prompts/igor.md \
    --dry-run
# (no-op, just confirm no side-effects)
```

Затем явный welcome через мини-скрипт (или добавить отдельную команду `--send-welcome-only`):

```bash
python3 -c "
import os
from scripts.onboard import welcome_sender
text = welcome_sender.build_welcome_text(name='Игорь', style='ty', inviter_name='Александр')
msg_id = welcome_sender.send_welcome(chat_id=830908046, text=text)
print(f'Sent message_id={msg_id}')
"
```

- [ ] **Step 3: Confirm delivery in agent_conversations log**

Welcome пишется в `agent_conversations` если будем интегрировать это — но в текущей реализации `welcome_sender.send_welcome` НЕ пишет в БД. Это намеренно: welcome — system message от бота, не agent reply. Логировать можно вручную:

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"INSERT INTO agent_conversations(user_id, role, content, source) \
          VALUES (830908046, 'assistant', \
            '[{\\\"type\\\":\\\"text\\\",\\\"text\\\":\\\"<welcome text>\\\"}]'::jsonb, \
            'onboarding_welcome');\""
```

(Или скипнуть этот шаг — welcome виден в Telegram'е и в логах бота.)

- [ ] **Step 4: Watch for Igor's response**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"SELECT created_at, role, source, LEFT(content::text, 200) \
          FROM agent_conversations \
          WHERE user_id=830908046 \
          ORDER BY created_at DESC LIMIT 5;\""
```

Ожидаем что Игорь напишет что-то и агент ответит используя KB.

---

## Task 16: Final regression sweep

- [ ] **Step 1: Verify all 5 known users**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "docker exec healthvault_postgres psql -U healthvault -d healthvault \
     -c \"SELECT telegram_id, first_name, cohort, pack_name, \
                LENGTH(COALESCE(agent_system_prompt,'')) as prompt_len \
          FROM users \
          WHERE telegram_id IN (895655, 33831673, 836757955, 1137554647, 830908046) \
          ORDER BY telegram_id;\""
```

Expected:
- 895655 Alex owner bariatric 8111 (unchanged)
- 33831673 Павел family generic ~10873 (unchanged)
- 836757955 Andrey early_user cardiac ~10362 (unchanged)
- 1137554647 Олег family generic ~1270 (unchanged)
- 830908046 Игорь **family respiratory_allergic ~8000+** (NEW)

- [ ] **Step 2: List all kb_*.json on server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASSWORD" ssh root@116.203.213.137 \
    "ls -la /opt/healthvault/kb_*.json"
```

Expected: 3 files (Pavel, Andrey, Igor). Pavel/Andrey unchanged dates, Igor new.

- [ ] **Step 3: Run full test suite**

```bash
python3 -m pytest tests/ -v 2>&1 | tail -50
```

Expected: всё что было зелёным — остаётся зелёным. Новые тесты тоже зелёные.

- [ ] **Step 4: Push to remote**

```bash
git push origin main
```

---

## Self-Review (executed inline)

**1. Spec coverage:**

- §2 scope CLI скрипт — Task 8 ✓
- §2 scope шаблон промпта — Task 4 ✓
- §2 scope реестр packs — Task 1 ✓
- §2 scope подключение Игоря — Tasks 11-15 ✓
- §2 scope документация — Task 9 ✓
- §2 scope тесты — Tasks 1, 2, 3, 5, 6, 7, 8 ✓
- §2 scope E2E smoke — Task 14 ✓
- §6 защита от регрессий — Tasks 10, 16 ✓
- §7 полный доступ через бота — проверен в Task 14 (vit D, allergies, BP-fallback) ✓
- §8 риски — митигации заложены: dry-run (Task 12), --from-file (Task 12 Step 4), snapshot (Task 2), atomic scp (Task 6), retry/fallback (Task 5)
- §10 hooks для C — структура пакета `scripts/onboard/` с разделёнными модулями ✓

Никаких неосвещённых требований.

**2. Placeholder scan:** Поискал «TBD», «TODO», «implement later», «add appropriate» — не нашёл. Все шаги содержат конкретный код или конкретные команды.

**3. Type consistency:**
- `PersonaInput` / `PersonaBlocks` — определены в Task 5, используются в Task 8 — поля совпадают.
- `ServerConfig` / `UserServerState` / `DeployResult` — определены в Task 6, используются в Task 8 — совпадают.
- `UserSnapshot` — Task 2, используется в Task 8 — совпадает.
- `validate_kb()` возвращает `KbSummary` — Task 3, используется в Task 8 — совпадает.
- `get_pack(name)` — Task 1, используется в Tasks 5 и 8 — сигнатура совпадает.
- `build_welcome_text(name, style, inviter_name)` / `send_welcome(chat_id, text)` — Task 7, используется в Tasks 8 и 15 — совпадает.

**4. One sanity edit:** В Task 8 cli imports — `from scripts.onboard import kb_validator, persona_generator, server_deployer, snapshot, welcome_sender`. Все эти модули созданы в Tasks 2, 3, 5, 6, 7 соответственно. Все по плану.

План complete.

---

## Execution

Plan complete and saved to [docs/superpowers/plans/2026-05-22-igor-botkin-onboarding.md](docs/superpowers/plans/2026-05-22-igor-botkin-onboarding.md).

Two execution options:

1. **Subagent-Driven (recommended)** — диспетчирую свежий subagent на каждую Task, ревьюю между Task'ами, быстрая итерация
2. **Inline Execution** — выполняю Task'и в этой сессии через executing-plans, batch с чекпойнтами для ревью

Какой подход?
