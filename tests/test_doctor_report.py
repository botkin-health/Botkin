"""Тесты doctor-view отчёта для врача (#290).

Чистый рендерер (данные→HTML) тестируется без БД; ассемблер (БД→данные) —
на in-memory SQLite (fixture test_db), проверяя фильтр user_id, парсинг
онбординга и деградацию при пустых данных.
"""

from datetime import date, datetime

from database.models import SupplementLog, User
from services.doctor_report import (
    DISCLAIMER,
    SECTION_ORDER,
    DoctorReport,
    ReportSection,
    build_doctor_report_html,
    render_doctor_report_html,
)


def _sample_report() -> DoctorReport:
    return DoctorReport(
        patient_label="Пациент",
        generated_at="2026-07-08",
        period="данные на 2026-07-08",
        sections=[
            ReportSection("problems", "Проблемы и диагнозы", ["Гипертония"], self_reported=True),
            ReportSection("allergies", "Аллергии и непереносимости", [], self_reported=True),
            ReportSection("medications", "Лекарства и добавки", ["Витамин D3 2000 МЕ"], self_reported=True),
            ReportSection("results", "Результаты исследований", ["Глюкоза: 5.1 ммоль/л (2026-06-09)"]),
            ReportSection("vitals", "Витальные показатели", ["АД: 120/80 (2026-06-01)"]),
            ReportSection("social", "Образ жизни", []),
        ],
    )


# ── Renderer (pure) ──────────────────────────────────────────────────────────


def test_render_sections_in_ips_order():
    """Секции идут в клиническом порядке IPS (Проблемы→…→Образ жизни)."""
    out = render_doctor_report_html(_sample_report())
    positions = [out.index(title) for _, title in SECTION_ORDER]
    assert positions == sorted(positions)


def test_render_includes_disclaimer():
    """Дисклеймер «wellness, не диагноз» присутствует."""
    out = render_doctor_report_html(_sample_report())
    assert "не диагноз" in DISCLAIMER
    assert "не диагноз" in out


def test_render_includes_header():
    """Header содержит идентификацию пациента и дату генерации."""
    out = render_doctor_report_html(_sample_report())
    assert "Пациент" in out
    assert "2026-07-08" in out


def test_render_self_reported_label():
    """Секция self_reported помечена «со слов пользователя»."""
    out = render_doctor_report_html(_sample_report())
    assert "со слов пользователя" in out


def test_render_empty_section_shows_note():
    """Пустая секция показывает empty_note, а не падает."""
    report = DoctorReport(
        patient_label="Пациент",
        generated_at="2026-07-08",
        period="",
        sections=[ReportSection("allergies", "Аллергии и непереносимости", [], empty_note="Нет данных")],
    )
    out = render_doctor_report_html(report)
    assert "Нет данных" in out


def test_render_escapes_user_text():
    """Пользовательский текст экранируется (XSS-safety)."""
    report = DoctorReport(
        patient_label="Пациент",
        generated_at="2026-07-08",
        period="",
        sections=[ReportSection("problems", "Проблемы и диагнозы", ["<script>alert(1)</script>"])],
    )
    out = render_doctor_report_html(report)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


# ── Assembler (DB) ───────────────────────────────────────────────────────────


def test_assemble_medications_filtered_by_user(test_db):
    """Добавки берутся только для запрошенного user_id (не суммируются чужие)."""
    test_db.add(
        User(
            telegram_id=895655,
            first_name="Игорь",
            is_active=True,
            cohort="owner",
            pack_name="generic",
            onboarding_data={"chronic_conditions": "Гипертония", "allergies": "пыльца"},
        )
    )
    test_db.add(User(telegram_id=111, first_name="Other", is_active=True, cohort="external", pack_name="generic"))
    test_db.add(SupplementLog(user_id=895655, date=date.today(), supplement_name="Магний", dosage="300 мг"))
    test_db.add(SupplementLog(user_id=111, date=date.today(), supplement_name="Ашваганда", dosage="600 мг"))
    test_db.commit()

    out = build_doctor_report_html(test_db, 895655)

    assert "Магний" in out  # своя добавка
    assert "Ашваганда" not in out  # чужая — не протекла
    assert "Гипертония" in out  # диагноз из онбординга
    assert "пыльца" in out  # аллергия из онбординга


def test_assemble_empty_user_does_not_crash(test_db):
    """Пользователь без данных — отчёт генерится с пометками «Нет данных»."""
    test_db.add(User(telegram_id=222, first_name="Пусто", is_active=True, cohort="external", pack_name="generic"))
    test_db.commit()

    out = build_doctor_report_html(test_db, 222)

    assert "Нет данных" in out
    assert "Пусто" in out


def test_assemble_generated_date_present(test_db):
    """Дата генерации проставляется (не пусто)."""
    test_db.add(User(telegram_id=333, first_name="Кто", is_active=True, cohort="external", pack_name="generic"))
    test_db.commit()
    out = build_doctor_report_html(test_db, 333)
    assert str(datetime.now().year) in out
