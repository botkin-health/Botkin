"""Тесты doctor-view отчёта для врача (#290).

Чистый рендерер (данные→HTML) тестируется без БД; ассемблер (БД→данные) —
на in-memory SQLite (fixture test_db), проверяя фильтр user_id, парсинг
онбординга и деградацию при пустых данных.
"""

from datetime import date, datetime

import pytest

import services.doctor_report as dr
from database.models import SupplementLog, User
from services.doctor_report import (
    DISCLAIMER,
    SECTION_ORDER,
    DoctorReport,
    ReportSection,
    build_doctor_report_html,
    doctor_report_filename,
    render_doctor_report_html,
    send_doctor_report_to_chat,
)


def _add_user(db, tid: int) -> None:
    db.add(User(telegram_id=tid, first_name="Тест", is_active=True, cohort="external", pack_name="generic"))
    db.commit()


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


# ── PDF-рендер и доставка ─────────────────────────────────────────────────────


def test_render_pdf_produces_pdf_bytes(test_db):
    """weasyprint даёт валидный PDF (skip, если GTK-libs недоступны)."""
    try:
        import weasyprint  # noqa: F401
    except Exception:
        pytest.skip("weasyprint/GTK-libs недоступны в этой среде")
    _add_user(test_db, 444)
    pdf = dr.render_doctor_report_pdf(test_db, 444)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_filename_is_ascii_pdf():
    """Имя файла — ASCII (кириллица в multipart Content-Disposition хрупка)."""
    fname = doctor_report_filename(date(2026, 7, 8))
    assert fname == "botkin_health_report_2026-07-08.pdf"
    assert fname.isascii()


def _stub_send(monkeypatch, *, ok: bool):
    """Подменить PDF-рендер, токен и requests.post для теста доставки."""
    dr._ensure_bot_path()
    monkeypatch.setattr("services.doctor_report.render_doctor_report_pdf", lambda db, uid: b"%PDF-1.4 fake")
    monkeypatch.setattr("bot_token.resolve_bot_token", lambda: "123:ABC")
    captured: dict = {}

    class _Resp:
        def json(self):
            return {"ok": ok, "description": None if ok else "bot was blocked", "result": {"message_id": 1}}

    def _fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["chat_id"] = data["chat_id"]
        captured["fname"] = files["document"][0]
        captured["mime"] = files["document"][2]
        return _Resp()

    monkeypatch.setattr("services.doctor_report.requests.post", _fake_post)
    return captured


def test_send_doctor_report_success(test_db, monkeypatch):
    """Успех: PDF уходит sendDocument с верным chat_id/именем/типом."""
    _add_user(test_db, 555)
    captured = _stub_send(monkeypatch, ok=True)
    out = send_doctor_report_to_chat(test_db, 555)
    assert out == {"status": "ok", "sent": True}
    assert "sendDocument" in captured["url"]
    assert captured["chat_id"] == 555
    assert captured["fname"].endswith(".pdf")
    assert captured["mime"] == "application/pdf"


def test_send_doctor_report_telegram_error(test_db, monkeypatch):
    """Telegram вернул ok=false → status error, sent False."""
    _add_user(test_db, 666)
    _stub_send(monkeypatch, ok=False)
    out = send_doctor_report_to_chat(test_db, 666)
    assert out["sent"] is False
    assert out["status"] == "error"


def test_send_doctor_report_render_failure(test_db, monkeypatch):
    """Сбой рендера PDF → error, requests не вызывается."""
    _add_user(test_db, 777)

    def _boom(db, uid):
        raise RuntimeError("gtk missing")

    monkeypatch.setattr("services.doctor_report.render_doctor_report_pdf", _boom)
    called = {"post": False}
    monkeypatch.setattr("services.doctor_report.requests.post", lambda *a, **k: called.__setitem__("post", True))
    out = send_doctor_report_to_chat(test_db, 777)
    assert out["sent"] is False
    assert "render-failed" in out["error"]
    assert called["post"] is False


def test_maccabi_hemoglobin_no_false_low_flag_end_to_end():
    """#295: maccabi-панель (g/dL без _unit_system) → to_canonical чинит Hb/MCHC →
    в отчёте «155 г/л» без ложного ↓ (репро прод-бага 10.07)."""
    from core.health.kb_schema import to_canonical
    from services.doctor_report import _results

    # values ровно как хранятся в прод blood_tests (снимок 830908046, 2026-06-09)
    values = {"hemoglobin": 15.5, "hemoglobin_ref": "13.5-18", "MCHC": 35.1, "hematocrit": 44.1}
    canon, _ = to_canonical(values)
    assert canon["Hb"] == 155.0
    assert canon["MCHC"] == 351.0

    bio = {"Hb": {"value": canon["Hb"], "date": "2026-06-09"}}
    lines = _results(bio)
    hb_line = next(line for line in lines if "155" in line)
    assert "↓" not in hb_line  # ложный флаг «низкий» ушёл
