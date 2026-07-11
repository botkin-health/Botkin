"""i18n для doctor-report (#300): словарь каркаса (ru/en), разрешение языка,
LLM-перевод свободного текста.

Гибрид: каркас (заголовки/единицы/дисклеймер) — детерминированный словарь;
свободный текст пользователя (диагнозы/аллергии/лекарства) — translate_freetext.
Числа/даты/нормы/флаги ↑↓ здесь не участвуют — они форматируются в doctor_report.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("ru", "en")

# Секции free-text, которые уходят в LLM-перевод (остальные — структурированы).
FREE_TEXT_SECTIONS = ("problems", "allergies", "medications")

CHROME = {
    "ru": {
        "html_lang": "ru",
        "report_title": "Отчёт о здоровье",
        "generated": "Сформирован",
        "period_prefix": "данные на",
        "patient_fallback": "Пациент",
        "self_reported": "(со слов пользователя)",
        "no_data": "Нет данных",
        "sections": {
            "problems": "Проблемы и диагнозы",
            "allergies": "Аллергии и непереносимости",
            "medications": "Лекарства и добавки",
            "results": "Результаты исследований",
            "vitals": "Витальные показатели",
            "social": "Образ жизни",
        },
        "bp_label": "АД",
        "bp_unit": "мм рт.ст.",
        "weight_label": "Вес",
        "weight_unit": "кг",
        "fat_label": "жир",
        "workouts_tpl": "Тренировок за {days} дней: {n}",
        "caption": (
            "📄 Отчёт о здоровье для врача. Сформирован автоматически из ваших данных "
            "в Botkin (wellness-сервис, не диагноз). Можно переслать врачу."
        ),
        "disclaimer": (
            "Отчёт сформирован автоматически из данных, которые пользователь вносил "
            "самостоятельно в приложение Botkin (wellness-сервис): фото/текст еды, "
            "показания устройств, ответы анкеты. Это не медицинский документ и не диагноз, "
            "часть сведений приведена со слов пользователя. Требования 152-ФЗ соблюдаются: "
            "отчёт формируется по запросу самого пользователя."
        ),
        "status_preparing": "⏳ Готовлю PDF-отчёт для врача…",
        "status_done": "✅ Готово — отчёт отправлен файлом выше, можно переслать врачу.",
        "status_failed": "❌ Не удалось сформировать отчёт. Попробуй позже.",
        "lang_hint": "Доступные языки: ru, en. Генерирую на языке по умолчанию.",
    },
    "en": {
        "html_lang": "en",
        "report_title": "Health Report",
        "generated": "Generated",
        "period_prefix": "data as of",
        "patient_fallback": "Patient",
        "self_reported": "(self-reported)",
        "no_data": "No data",
        "sections": {
            "problems": "Problems and diagnoses",
            "allergies": "Allergies and intolerances",
            "medications": "Medications and supplements",
            "results": "Lab results",
            "vitals": "Vital signs",
            "social": "Lifestyle",
        },
        "bp_label": "BP",
        "bp_unit": "mmHg",
        "weight_label": "Weight",
        "weight_unit": "kg",
        "fat_label": "body fat",
        "workouts_tpl": "Workouts in last {days} days: {n}",
        "caption": (
            "📄 Health report for your doctor. Generated automatically from your data "
            "in Botkin (a wellness service, not a diagnosis). You can forward it to a physician."
        ),
        "disclaimer": (
            "This report was generated automatically from data the user entered themselves "
            "into the Botkin app (a wellness service): food photos/text, device readings, "
            "questionnaire answers. It is not a medical document or a diagnosis; some entries "
            "are self-reported. It was produced at the user's own request."
        ),
        "status_preparing": "⏳ Preparing your PDF health report…",
        "status_done": "✅ Done — the report was sent as a file above, you can forward it to your doctor.",
        "status_failed": "❌ Could not build the report. Please try again later.",
        "lang_hint": "Available languages: ru, en. Generating in the default language.",
    },
}


def resolve_report_language(explicit: str | None, tg_language_code: str | None) -> str:
    """Разрешить язык отчёта. Явный валидный выбор перебивает всё; иначе en-код → en; иначе ru."""
    if explicit in SUPPORTED_LANGS:
        return explicit
    if tg_language_code and str(tg_language_code).lower().startswith("en"):
        return "en"
    return "ru"
