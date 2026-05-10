#!/usr/bin/env python3
"""
Генератор «Журнала обследований» из knowledge_base.json любого человека.

Что делает:
  Читает knowledge_base.json, находит САМЫЕ СВЕЖИЕ записи по каждой категории
  обследований (ОАМ, УЗИ, ЭКГ, колоноскопия, ...) и формирует markdown-таблицу
  для вставки в PROFILE.md этого человека.

Зачем:
  Без этой таблицы AI-агенты при медицинских вопросах часто промахиваются —
  забывают про существующие свежие исследования и предлагают сделать то,
  что уже сделано. PROFILE.md = первый файл который читается → AI сразу
  видит инвентарь обследований с датами и не «изобретает велосипед».

Использование:
  # Для конкретного человека (по имени папки на Google Drive):
  python3 scripts/generate_exam_journal.py "Александр Лысковский — Здоровье"
  python3 scripts/generate_exam_journal.py "Андрей Лысковский — Здоровье"

  # Или с прямым путём к knowledge_base.json:
  python3 scripts/generate_exam_journal.py --kb /path/to/knowledge_base.json

  # С автозаписью в PROFILE.md (между маркерами):
  python3 scripts/generate_exam_journal.py "Имя — Здоровье" --update-profile

Интегрируется в PROFILE.md между маркерами:
  <!-- EXAM_JOURNAL_START -->
  ...сгенерированная таблица...
  <!-- EXAM_JOURNAL_END -->
"""

from __future__ import annotations
import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
import sys

GD_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault"
TODAY = date.today()


def _days_ago(d: str) -> int | None:
    try:
        return (TODAY - date.fromisoformat(d)).days
    except Exception:
        return None


def _flag(days: int | None) -> str:
    if days is None:
        return ""
    if days < 365:
        return "✅"
    if days < 730:
        return "⚠"
    return "🚨"


def _age_label(days: int | None) -> str:
    if days is None:
        return "—"
    if days < 30:
        return f"{days} дн"
    if days < 365:
        return f"{days // 30} мес"
    return f"{round(days / 365, 1)} года"


# Категории обследований и как их искать в knowledge_base.json
# (секция, фильтр-функция или None если все записи секции подходят)
CATEGORIES: list[tuple[str, str, callable | None]] = [
    (
        "Анализы крови (комплекс)",
        "blood_tests",
        lambda t: "comprehensive" in (t.get("analysis_type") or "").lower() or len(t.get("values") or {}) > 30,
    ),
    ("Анализы мочи (ОАМ)", "urine_tests", None),
    (
        "УЗИ органов брюшной полости",
        "ultrasound",
        lambda t: "брюшной" in (t.get("analysis_type") or "").lower() or "abdomen" in (t.get("file") or "").lower(),
    ),
    (
        "УЗИ почек / мочевыделительной",
        "ultrasound",
        lambda t: "поч" in (t.get("analysis_type") or "").lower() or "urinary" in (t.get("file") or "").lower(),
    ),
    (
        "УЗИ простаты",
        "ultrasound",
        lambda t: "простат" in (t.get("analysis_type") or "").lower() or "prostate" in (t.get("file") or "").lower(),
    ),
    (
        "УЗИ щитовидной железы",
        "ultrasound",
        lambda t: "щитовид" in (t.get("analysis_type") or "").lower() or "thyroid" in (t.get("file") or "").lower(),
    ),
    (
        "УЗИ малого таза (ж)",
        "ultrasound",
        lambda t: "малого таза" in (t.get("analysis_type") or "").lower() or "pelvis" in (t.get("file") or "").lower(),
    ),
    (
        "УЗИ молочных желёз (ж)",
        "ultrasound",
        lambda t: "молочн" in (t.get("analysis_type") or "").lower() or "breast" in (t.get("file") or "").lower(),
    ),
    (
        "УЗДГ БЦА (брахиоцефальные артерии)",
        "ultrasound",
        lambda t: (
            "бца" in (t.get("analysis_type") or "").lower()
            or "брахиоцеф" in (t.get("analysis_type") or "").lower()
            or "shei" in (t.get("file") or "").lower()
            or "узд" in (t.get("analysis_type") or "").lower()
        ),
    ),
    (
        "ЭхоКГ (УЗИ сердца)",
        "ultrasound",
        lambda t: (
            "эхокг" in (t.get("analysis_type") or "").lower()
            or "сердц" in (t.get("analysis_type") or "").lower()
            or "echo" in (t.get("file") or "").lower()
        ),
    ),
    ("ЭКГ", "ecg", None),
    (
        "Колоноскопия / ЭГДС",
        "medical_records",
        lambda t: any(
            p in json.dumps(t, ensure_ascii=False).lower() for p in ("колоноск", "эгдс", "гастроск", "colonosc")
        ),
    ),
    ("Спирометрия", "spirometry", None),
    (
        "Денситометрия (DEXA)",
        "ultrasound",
        lambda t: "денсит" in (t.get("analysis_type") or "").lower() or "dexa" in (t.get("file") or "").lower(),
    ),
    (
        "МРТ",
        "medical_records",
        lambda t: "мрт" in json.dumps(t, ensure_ascii=False).lower() or "mri" in (t.get("file") or "").lower(),
    ),
    (
        "КТ",
        "medical_records",
        lambda t: (
            re.search(r"(?<!\w)кт(?!\w)", json.dumps(t, ensure_ascii=False).lower())
            or "ct_" in (t.get("file") or "").lower()
        ),
    ),
]


def _imaging_items(kb: dict, modality: str) -> list[dict]:
    """Возвращает список записей из imaging.{modality} (если imaging — dict) или из medical_records (fallback)."""
    imaging = kb.get("imaging") or {}
    if isinstance(imaging, dict):
        entries = imaging.get(modality) or []
        return [e for e in entries if isinstance(e, dict) and e.get("date")]
    return []


def build_journal(kb: dict) -> str:
    rows = []
    for label, sect, filt in CATEGORIES:
        items = kb.get(sect) or []
        if filt:
            items = [t for t in items if filt(t)]

        # For КТ / МРТ: merge with imaging.ct / imaging.mri (whichever is newer wins)
        if label == "КТ":
            items = list(items) + _imaging_items(kb, "ct")
        elif label == "МРТ":
            items = list(items) + _imaging_items(kb, "mri")

        if not items:
            continue  # не показываем пустые категории — слишком шумно для женских позиций у мужчин и т.п.
        items.sort(key=lambda t: t.get("date", ""), reverse=True)
        # Deduplicate by date (keep first occurrence after sort)
        seen_dates: set[str] = set()
        unique_items = []
        for it in items:
            d_ = it.get("date", "")
            if d_ not in seen_dates:
                seen_dates.add(d_)
                unique_items.append(it)
        last = unique_items[0]
        d = last.get("date") or "—"
        da = _days_ago(d)
        age = _age_label(da)
        flag = _flag(da)
        src = last.get("source") or last.get("laboratory") or "—"
        if isinstance(src, str) and len(src) > 40:
            src = src[:40] + "…"
        fl = (last.get("file") or "").split("/")[-1] or "—"
        rows.append(f"| {label} | {d} | {age} {flag} | {src} | `{fl}` |")

    header = (
        f"<!-- EXAM_JOURNAL_START — автогенерация от {TODAY.isoformat()} -->\n"
        f"### 🩺 Журнал обследований (на {TODAY.strftime('%d.%m.%Y')})\n\n"
        f"> Источник истины: `knowledge_base.json` соответствующих секций. "
        f"Сгенерировано `scripts/generate_exam_journal.py` — не править руками.\n\n"
        f"| Что | Дата | Давность | Кто/где | Файл |\n"
        f"|---|---|---|---|---|\n"
    )
    body = "\n".join(rows)
    footer = "\n<!-- EXAM_JOURNAL_END -->\n"
    return header + body + footer


def update_profile_md(profile_path: Path, journal_md: str) -> None:
    if not profile_path.exists():
        print(f"⚠️  PROFILE.md не найден: {profile_path}")
        print("Создаю новый файл с журналом обследований.")
        profile_path.write_text(f"# Профиль\n\n{journal_md}\n", encoding="utf-8")
        return
    content = profile_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"<!--\s*EXAM_JOURNAL_START.*?<!--\s*EXAM_JOURNAL_END\s*-->\n?",
        re.DOTALL,
    )
    if pattern.search(content):
        new_content = pattern.sub(journal_md, content)
    else:
        # Вставляем в конец файла
        new_content = content.rstrip() + "\n\n" + journal_md
    profile_path.write_text(new_content, encoding="utf-8")
    print(f"✅ Обновлён {profile_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "person_dir", nargs="?", help='Имя папки на Google Drive (например "Александр Лысковский — Здоровье")'
    )
    p.add_argument("--kb", help="Прямой путь к knowledge_base.json (вместо имени папки)")
    p.add_argument("--update-profile", action="store_true", help="Записать журнал в PROFILE.md этого человека")
    p.add_argument("--print", action="store_true", help="Только распечатать в stdout, не записывать")
    args = p.parse_args()

    if args.kb:
        kb_path = Path(args.kb)
        profile_path = kb_path.parent / "PROFILE.md"
    elif args.person_dir:
        kb_path = GD_HEALTH / args.person_dir / "knowledge_base.json"
        profile_path = GD_HEALTH / args.person_dir / "PROFILE.md"
    else:
        p.error("укажи person_dir или --kb")
        return

    if not kb_path.exists():
        print(f"❌ Не найден: {kb_path}")
        sys.exit(1)
    kb = json.loads(kb_path.read_text(encoding="utf-8"))
    journal = build_journal(kb)

    if args.print or not args.update_profile:
        print(journal)
    if args.update_profile:
        update_profile_md(profile_path, journal)


if __name__ == "__main__":
    main()
