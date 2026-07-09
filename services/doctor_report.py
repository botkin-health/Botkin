"""PDF-отчёт для врача (#290) — сборка данных и рендер HTML.

Модель содержания — International Patient Summary (ISO 27269): секции идут в
клиническом порядке Проблемы → Аллергии → Лекарства → Результаты → Витальные →
Образ жизни. Артефакт — человекочитаемый HTML (→ PDF в render_doctor_report_pdf, Ф2).

Инварианты:
- только чтение БД (никаких записей);
- SQL по `supplements_log` — всегда с фильтром user_id (иначе смешаются пользователи);
- биомаркеры канонизируются через kb_schema (`_load_biomarkers_from_db` → aggregate_biomarkers);
- частичные секции (проблемы/аллергии/лекарства из онбординга) помечаются «со слов пользователя».
"""

from __future__ import annotations

import html
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Presentation-слой биомаркеров (label/unit/референсы) — то, чего нет в kb_schema.
# Переиспользуем, чтобы не дублировать RU-названия и границы норм.
from core.reports.biomarker_dynamics import MARKER_CONFIG

# Окно «недавних» добавок и активности.
_SUPPLEMENTS_WINDOW_DAYS = 90
_ACTIVITY_WINDOW_DAYS = 30

DISCLAIMER = (
    "Отчёт сформирован автоматически из данных, которые пользователь вносил "
    "самостоятельно в приложение Botkin (wellness-сервис): фото/текст еды, "
    "показания устройств, ответы анкеты. Это не медицинский документ и не диагноз, "
    "часть сведений приведена со слов пользователя. Требования 152-ФЗ соблюдаются: "
    "отчёт формируется по запросу самого пользователя."
)

# Клинический порядок секций (IPS / ISO 27269).
SECTION_ORDER: list[tuple[str, str]] = [
    ("problems", "Проблемы и диагнозы"),
    ("allergies", "Аллергии и непереносимости"),
    ("medications", "Лекарства и добавки"),
    ("results", "Результаты исследований"),
    ("vitals", "Витальные показатели"),
    ("social", "Образ жизни"),
]


@dataclass
class ReportSection:
    key: str
    title: str
    items: list[str] = field(default_factory=list)
    self_reported: bool = False
    empty_note: str = "Нет данных"


@dataclass
class DoctorReport:
    patient_label: str
    generated_at: str
    period: str
    sections: list[ReportSection]


def _esc(value: object) -> str:
    return html.escape(str(value))


# ── Рендер (чистый, без БД) ──────────────────────────────────────────────────


def render_doctor_report_html(report: DoctorReport) -> str:
    """DoctorReport → печатный A4 HTML в клиническом порядке секций."""
    blocks: list[str] = []
    for section in report.sections:
        note = ' <span class="self">(со слов пользователя)</span>' if section.self_reported else ""
        if section.items:
            lis = "\n".join(f"      <li>{_esc(it)}</li>" for it in section.items)
            body = f"    <ul>\n{lis}\n    </ul>"
        else:
            body = f'    <p class="empty">{_esc(section.empty_note)}</p>'
        blocks.append(f"  <section>\n    <h2>{_esc(section.title)}{note}</h2>\n{body}\n  </section>")

    sections_html = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Отчёт для врача — {_esc(report.patient_label)}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font-family: "DejaVu Sans", sans-serif; font-size: 11pt; color: #1a1a1a; line-height: 1.4; }}
  header {{ border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 14px; }}
  header h1 {{ font-size: 15pt; margin: 0 0 4px; }}
  header .meta {{ font-size: 9.5pt; color: #555; }}
  section {{ margin: 12px 0; page-break-inside: avoid; }}
  h2 {{ font-size: 12pt; border-bottom: 1px solid #ccc; padding-bottom: 3px; margin: 0 0 6px; }}
  ul {{ margin: 4px 0 4px 18px; padding: 0; }}
  li {{ margin: 2px 0; }}
  .self {{ font-size: 8.5pt; font-weight: normal; color: #888; }}
  .empty {{ color: #999; font-style: italic; margin: 4px 0; }}
  .disclaimer {{ margin-top: 18px; padding-top: 8px; border-top: 1px solid #ccc;
                 font-size: 8.5pt; color: #777; }}
</style>
</head>
<body>
  <header>
    <h1>Отчёт о здоровье — {_esc(report.patient_label)}</h1>
    <div class="meta">Сформирован: {_esc(report.generated_at)} · {_esc(report.period)}</div>
  </header>
{sections_html}
  <p class="disclaimer">{_esc(DISCLAIMER)}</p>
</body>
</html>"""


# ── Сборка данных из БД ───────────────────────────────────────────────────────


def _ensure_bot_path() -> None:
    """telegram-bot/ в sys.path (там живёт dashboard_generator)."""
    bot_dir = Path(__file__).resolve().parent.parent / "telegram-bot"
    if str(bot_dir) not in sys.path:
        sys.path.insert(0, str(bot_dir))


def _coerce_dict(raw: object) -> dict:
    """onboarding_data может прийти dict (ORM/JSONB) или str (raw SQL в SQLite)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _onboarding_list(onboarding: Optional[dict], keys: tuple[str, ...]) -> list[str]:
    """Достать список значений из онбординга по первому подходящему ключу.

    Значение может быть списком или строкой (тогда режем по запятой/переносу).
    """
    if not onboarding:
        return []
    for key in keys:
        val = onboarding.get(key)
        if not val:
            continue
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        parts = [p.strip() for p in str(val).replace("\n", ",").split(",")]
        return [p for p in parts if p]
    return []


def _problems(onboarding: Optional[dict]) -> list[str]:
    return _onboarding_list(onboarding, ("chronic_conditions", "chronic_diagnoses", "diagnoses", "conditions"))


def _allergies(onboarding: Optional[dict]) -> list[str]:
    return _onboarding_list(onboarding, ("allergies", "food_allergies", "allergy"))


def _medications(db: Session, user_id: int, onboarding: Optional[dict]) -> list[str]:
    """Лекарства из онбординга + недавние добавки из supplements_log (фильтр user_id)."""
    items = _onboarding_list(onboarding, ("current_medications", "medications"))
    since = date.today() - timedelta(days=_SUPPLEMENTS_WINDOW_DAYS)
    rows = db.execute(
        text(
            "SELECT supplement_name, dosage, MAX(date) AS last_date "
            "FROM supplements_log "
            "WHERE user_id = :uid AND date >= :since "
            "GROUP BY supplement_name, dosage "
            "ORDER BY last_date DESC"
        ),
        {"uid": user_id, "since": since},
    ).fetchall()
    for row in rows:
        name = row.supplement_name
        items.append(f"{name} — {row.dosage}" if row.dosage else str(name))
    return items


def _results(bio: dict) -> list[str]:
    """Биомаркеры (канон) → строки label: value unit (date) [↑/↓ вне нормы]."""
    lines: list[tuple[str, str]] = []
    for canon, rec in bio.items():
        value = rec.get("value")
        if value is None:
            continue
        cfg = MARKER_CONFIG.get(canon, {})
        label = cfg.get("label", canon)
        unit = cfg.get("unit", "")
        flag = ""
        low, high = cfg.get("ref_low"), cfg.get("ref_high")
        try:
            if high is not None and value > high:
                flag = " ↑"
            elif low is not None and value < low:
                flag = " ↓"
        except TypeError:
            flag = ""
        unit_part = f" {unit}" if unit else ""
        date_part = f" ({rec['date']})" if rec.get("date") else ""
        lines.append((label, f"{label}: {value}{unit_part}{date_part}{flag}"))
    return [line for _, line in sorted(lines, key=lambda x: x[0])]


def _vitals(db: Session, user_id: int) -> list[str]:
    """Последние АД и вес/жир (по одному замеру — реальные, не средние)."""
    items: list[str] = []
    bp = db.execute(
        text(
            "SELECT systolic, diastolic, DATE(measured_at) AS d "
            "FROM blood_pressure_logs WHERE user_id = :uid "
            "ORDER BY measured_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).fetchone()
    if bp and bp.systolic and bp.diastolic:
        items.append(f"АД: {bp.systolic}/{bp.diastolic} мм рт.ст. ({bp.d})")
    w = db.execute(
        text(
            "SELECT weight, body_fat, DATE(measured_at) AS d "
            "FROM weights WHERE user_id = :uid ORDER BY measured_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).fetchone()
    if w and w.weight is not None:
        fat = f", жир {round(w.body_fat, 1)}%" if w.body_fat is not None else ""
        items.append(f"Вес: {round(w.weight, 1)} кг{fat} ({w.d})")
    return items


def _social(db: Session, user_id: int) -> list[str]:
    """Лёгкая сводка образа жизни: тренировки за последний месяц."""
    since = date.today() - timedelta(days=_ACTIVITY_WINDOW_DAYS)
    n = db.execute(
        text("SELECT COUNT(*) AS n FROM workouts WHERE user_id = :uid AND date >= :since"),
        {"uid": user_id, "since": since},
    ).scalar()
    items: list[str] = []
    if n:
        items.append(f"Тренировок за {_ACTIVITY_WINDOW_DAYS} дней: {n}")
    return items


def _load_biomarkers(db: Session, user_id: int) -> dict:
    """Канонизированные биомаркеры; при сбое импорта/чтения — пустой словарь."""
    try:
        _ensure_bot_path()
        from dashboard_generator import _load_biomarkers_from_db  # noqa: PLC0415

        return _load_biomarkers_from_db(db, user_id) or {}
    except Exception:
        return {}


def assemble_doctor_report(db: Session, user_id: int) -> DoctorReport:
    """Собрать DoctorReport из БД в клиническом порядке секций IPS."""
    user = db.execute(
        text("SELECT first_name, last_name, onboarding_data FROM users WHERE telegram_id = :uid"),
        {"uid": user_id},
    ).fetchone()
    onboarding = _coerce_dict(user.onboarding_data) if user else {}
    name_parts = [user.first_name, getattr(user, "last_name", None)] if user else []
    patient_label = " ".join(p for p in name_parts if p) or "Пациент"

    bio = _load_biomarkers(db, user_id)
    builders = {
        "problems": lambda: _problems(onboarding),
        "allergies": lambda: _allergies(onboarding),
        "medications": lambda: _medications(db, user_id, onboarding),
        "results": lambda: _results(bio),
        "vitals": lambda: _vitals(db, user_id),
        "social": lambda: _social(db, user_id),
    }
    self_reported = {"problems", "allergies", "medications"}

    sections = [
        ReportSection(
            key=key,
            title=title,
            items=builders[key](),
            self_reported=key in self_reported,
        )
        for key, title in SECTION_ORDER
    ]

    today = datetime.now(timezone.utc).date().isoformat()
    return DoctorReport(
        patient_label=patient_label,
        generated_at=today,
        period=f"данные на {today}",
        sections=sections,
    )


def build_doctor_report_html(db: Session, user_id: int) -> str:
    """БД → человекочитаемый HTML отчёта для врача (Проблемы→…→Образ жизни)."""
    return render_doctor_report_html(assemble_doctor_report(db, user_id))


# ── PDF-рендер и доставка ─────────────────────────────────────────────────────

_CAPTION = (
    "📄 Отчёт о здоровье для врача. Сформирован автоматически из ваших данных в Botkin "
    "(wellness-сервис, не диагноз). Можно переслать врачу."
)


def render_doctor_report_pdf(db: Session, user_id: int) -> bytes:
    """HTML отчёта врачу → PDF.

    weasyprint импортируется лениво: его рантайм требует системные GTK-libs
    (см. Dockerfile/Dockerfile.bot), которых нет в тест-среде без них.
    """
    html_str = build_doctor_report_html(db, user_id)
    from weasyprint import HTML  # noqa: PLC0415

    return HTML(string=html_str).write_pdf()


def doctor_report_filename(today: Optional[date] = None) -> str:
    # ASCII-имя намеренно: кириллица в Content-Disposition multipart зависит от
    # RFC 2231-кодирования и часть Telegram-клиентов показывает её криво.
    d = (today or datetime.now(timezone.utc).date()).isoformat()
    return f"botkin_health_report_{d}.pdf"


def send_doctor_report_to_chat(db: Session, user_id: int, *, timeout: int = 30) -> dict:
    """Сгенерировать PDF и отправить пользователю Telegram-документом.

    Единый путь доставки для кнопки мини-аппа и (в follow-up) агент-тула.
    Ошибки не пробрасываются — возвращаются в словаре {status, sent, error?}.
    """
    try:
        pdf = render_doctor_report_pdf(db, user_id)
    except Exception as e:
        logger.error("doctor_report render failed for %s: %s", user_id, e, exc_info=True)
        return {"status": "error", "error": f"render-failed: {e}", "sent": False}

    _ensure_bot_path()
    from bot_token import resolve_bot_token  # noqa: PLC0415

    token = resolve_bot_token()
    if not token:
        return {"status": "error", "error": "bot-token-missing", "sent": False}

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": user_id, "caption": _CAPTION},
            files={"document": (doctor_report_filename(), pdf, "application/pdf")},
            timeout=timeout,
        )
        result = resp.json()
        if not result.get("ok"):
            logger.warning("sendDocument failed for %s: %s", user_id, result)
            return {"status": "error", "error": f"telegram: {result.get('description')}", "sent": False}
    except Exception as e:
        logger.error("sendDocument exception for %s: %s", user_id, e, exc_info=True)
        return {"status": "error", "error": f"telegram-exception: {e}", "sent": False}

    return {"status": "ok", "sent": True}
