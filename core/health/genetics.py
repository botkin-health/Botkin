"""Результаты ДНК-теста пациента — чтение из KB и применение в работе агента.

Генетика отличается от остальных данных тем, что она не устаревает и касается
почти всего: подбора питания и добавок, выбора препарата и дозы, трактовки
анализов, оценки рисков. Поэтому её не гоняют инструментом по запросу, а
приклеивают к системному промпту целиком — блок стабилен per-user и попадает
в кэшируемую часть, то есть не инвалидирует кэш на каждом сообщении.

Предыстория: сначала данные лежали в KB и читались только правилом «вопрос про
лекарство → загляни в фармакогенетику». Проверка 20.09.2026 показала, что при
вопросе про билирубин агент про носительство синдрома Жильбера не вспоминал —
запись была рядом, но правило на неё не распространялось. Перечислять темы
оказалось тупиковым путём: их столько же, сколько тем у медицины.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Ключи в kb.agent_corrections, куда складывается разбор ДНК-теста.
GENETICS_KEYS = (
    "genetics_pharmacogenetics",
    "genetics_findings",
    "genetics_excluded_diagnoses",
)

# Потолок на блок в промпте. Данных у одного человека примерно 5-6 тыс. знаков;
# лимит защищает от разрастания, если записей станет больше.
MAX_BLOCK_CHARS = 8000

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def kb_path_for(user) -> Optional[Path]:
    """Путь к KB-файлу пользователя. Повторяет логику webhook/agent_tools/common."""
    tid = getattr(user, "telegram_id", None)
    if tid is None:
        return None
    new_path = _PROJECT_ROOT / "data" / "kb" / f"kb_{tid}.json"
    if new_path.exists():
        return new_path
    legacy = _PROJECT_ROOT / f"kb_{tid}.json"
    if legacy.exists():
        return legacy
    if getattr(user, "cohort", None) == "owner":
        owner_kb = _PROJECT_ROOT / "knowledge_base.json"
        if owner_kb.exists():
            return owner_kb
    return None


def load_genetics(user) -> dict[str, str]:
    """Записи ДНК-теста из kb.agent_corrections. Пусто — если теста нет.

    Любой сбой чтения возвращает пустой словарь: отсутствие генетики не должно
    мешать агенту ответить.
    """
    path = kb_path_for(user)
    if path is None:
        return {}
    try:
        kb = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    corrections = kb.get("agent_corrections")
    if not isinstance(corrections, dict):
        return {}

    out: dict[str, str] = {}
    for key in GENETICS_KEYS:
        entry = corrections.get(key)
        if isinstance(entry, dict):
            value = entry.get("value")
        else:
            value = entry
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def genetics_prompt_block(user) -> str:
    """Блок генетики для системного промпта. Пустая строка, если теста нет."""
    data = load_genetics(user)
    if not data:
        return ""

    lines = [
        "\n\n## Генетика пациента (ДНК-тест)",
        "Постоянные данные, они не устаревают. Учитывай их ВО ВСЁМ: питание и",
        "добавки, выбор препарата и дозы, трактовка анализов, оценка рисков,",
        "любые рекомендации. Если тема разговора пересекается с чем-то ниже —",
        "скажи об этом САМ, не дожидаясь вопроса про генетику.",
        "Версию, помеченную ниже как исключённую, больше не предлагай.",
        "Чего ниже нет — того не выдумывай: так и скажи, что данных нет.",
    ]
    for key in GENETICS_KEYS:
        if key in data:
            lines.append("")
            lines.append(data[key])

    block = "\n".join(lines)
    if len(block) > MAX_BLOCK_CHARS:
        block = block[:MAX_BLOCK_CHARS] + "\n…(блок усечён, подробности — get_kb_value)"
    return block


# ── Проверка конкретного препарата ────────────────────────────────────────────

# Запись фармакогенетики — связный текст; режем на фразы, чтобы вернуть ровно ту,
# где упомянут препарат, а не весь абзац.
_SPLIT_RE = re.compile(r"(?<=[.;])\s+|\n+")
# Хвосты русских склонений: «симвастатина», «клопидогрелом» → общий корень.
_MIN_STEM = 5


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def _stem(word: str) -> str:
    """Грубый корень слова для сопоставления склонений."""
    w = _normalize(word).strip(" .,;:!?()[]«»\"'")
    if len(w) <= _MIN_STEM:
        return w
    # Отрезаем до трёх последних букв, но не короче _MIN_STEM.
    return w[: max(_MIN_STEM, len(w) - 3)]


def check_drug(user, drug_name: str) -> Optional[str]:
    """Найти в фармакогенетике фразу про этот препарат.

    Возвращает текст предупреждения или None. Сопоставление по корню слова,
    поэтому «симвастатина» находит «Симвастатин». Если препарата в записи нет —
    None: молчим, а не сочиняем.
    """
    if not drug_name or not drug_name.strip():
        return None
    data = load_genetics(user)
    text = data.get("genetics_pharmacogenetics")
    if not text:
        return None

    stems = [_stem(part) for part in re.split(r"[\s/,]+", drug_name) if len(part) > 3]
    stems = [s for s in stems if len(s) >= _MIN_STEM]
    if not stems:
        return None

    for segment in _SPLIT_RE.split(text):
        seg_norm = _normalize(segment)
        if any(stem in seg_norm for stem in stems):
            cleaned = segment.strip()
            if cleaned:
                return cleaned
    return None
