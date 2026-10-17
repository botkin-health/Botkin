"""Тексты вкладки «Состояние»: заголовки, подписи, next-best-action (ru/en).

⚠️ `ACTIONS` — ПЛЕЙСХОЛДЕРЫ, не медицинский совет. Формулировки должен написать/утвердить врач
проекта до показа клинике. Правило: без назначений лечения — только «обсудить с врачом»,
«пересдать», «проверить». Botkin — не медицинский сервис (docs/architecture/vision.md).
"""

from __future__ import annotations

UNITS = {
    "ru": {
        "h": "ч",
        "steps": "шаг",
        "ms": "мс",
        "bpm": "уд/мин",
        "kg": "кг",
        "pct": "%",
        "mmol": "ммоль/л",
        "mmhg": "мм рт. ст.",
    },
    "en": {
        "h": "h",
        "steps": "steps",
        "ms": "ms",
        "bpm": "bpm",
        "kg": "kg",
        "pct": "%",
        "mmol": "mmol/L",
        "mmhg": "mmHg",
    },
}

# Подписи агрегатов. {days} — длина окна, {bdays} — длина baseline.
LABELS = {
    "ru": {
        "mean": "среднее за {days} дн.",
        "median": "медиана {bdays} дн. до окна",
        "median_ok": "медиана {bdays} дн.",
        "stream": {
            "sleep": "Сон",
            "activity": "Активность",
            "hrv": "HRV",
            "heart": "Пульс",
            "weight": "Вес",
            "bp": "Давление",
            "glucose": "Глюкоза",
            "labs": "Анализы",
        },
        "ref_male_only": "Референсы пока заданы только для мужчин; значения показаны без оценки.",
        "ref_sex_not_set": "Пол не указан в профиле — значения показаны без оценки. Укажите пол, чтобы увидеть флаги.",
        "ref_male": "Референсы для взрослых мужчин (общая популяция).",
    },
    "en": {
        "mean": "{days}-day mean",
        "median": "median of {bdays} days before the window",
        "median_ok": "{bdays}-day median",
        "stream": {
            "sleep": "Sleep",
            "activity": "Activity",
            "hrv": "HRV",
            "heart": "Heart rate",
            "weight": "Weight",
            "bp": "Blood pressure",
            "glucose": "Glucose",
            "labs": "Lab results",
        },
        "ref_male_only": "Reference ranges are currently defined for adult men only; values are shown without assessment.",
        "ref_sex_not_set": "Sex is not set in the profile — values are shown without assessment. Set it to see flags.",
        "ref_male": "Reference ranges for adult men (general population).",
    },
}

# Заголовки и описания пунктов attention. Плейсхолдеры — в формате str.format.
ITEMS = {
    "ru": {
        "sleep": ("Сон короче обычного", "Средний сон за {days} дн. — {recent} ч (N={n}){cmp}"),
        "sleep_cmp": ", твоя норма за {bdays} дн. до этого — {base} ч (N={bn})",
        "hrv": (
            "HRV ниже обычного",
            "HRV (среднее за {days} дн.) — {recent} мс (N={n}) против нормы {base} мс (медиана {bdays} дн., N={bn})",
        ),
        "heart": (
            "Пульс выше обычного",
            "Пульс ({kind}, среднее за {days} дн.) — {recent} уд/мин (N={n}) против {base} уд/мин (медиана {bdays} дн., N={bn})",
        ),
        "heart_kind_resting": "покой",
        "heart_kind_mixed": "покой или средний за день",
        "activity_steps": (
            "Шагов меньше обычного",
            "Шагов в день (среднее за {days} дн.) — {recent} (N={n}) против {base} (медиана {bdays} дн., N={bn})",
        ),
        "activity_workouts": ("Нет тренировок", "За {days} дн. тренировок нет, за предыдущие 4 недели их было {prev}"),
        "bp_high": ("Давление ≥140/90 повторялось", "Замеров ≥140/90 за {bp_days} дн.: {cnt} из {n}"),
        "bp_avg": ("Давление выше 130/80", "Среднее за {bp_days} дн. — {sys}/{dia} мм рт. ст. (N={n})"),
        "glucose_tir": (
            "Глюкоза: мало времени в целевом диапазоне",
            "В диапазоне 3,9–10,0 ммоль/л — {tir} % времени за {days} дн. (точек: {n})",
        ),
        "glucose_tbr": (
            "Глюкоза: время ниже 3,9 ммоль/л",
            "Ниже 3,9 ммоль/л — {tbr} % времени за {days} дн. (точек: {n})",
        ),
        "weight": (
            "Вес заметно изменился",
            "С {d0} ({v0} кг) по {d1} ({v1} кг) — {delta} кг ({pct} %), по первому и последнему замеру",
        ),
        "lab_high": ("{label} выше нормы", "{value} {unit} ({date}), норма до {ref}"),
        "lab_low": ("{label} ниже нормы", "{value} {unit} ({date}), норма от {ref}"),
        "lab_prev": " · было {prev}",
        "labs_stale": ("Просрочены анализы: {n}", "Последний замер старше рекомендуемого срока: {names}"),
    },
    "en": {
        "sleep": ("Sleep shorter than usual", "Average sleep over {days} days is {recent} h (N={n}){cmp}"),
        "sleep_cmp": ", your usual over the previous {bdays} days is {base} h (N={bn})",
        "hrv": (
            "HRV below usual",
            "HRV ({days}-day mean) is {recent} ms (N={n}) vs usual {base} ms ({bdays}-day median, N={bn})",
        ),
        "heart": (
            "Heart rate above usual",
            "Heart rate ({kind}, {days}-day mean) is {recent} bpm (N={n}) vs {base} bpm ({bdays}-day median, N={bn})",
        ),
        "heart_kind_resting": "resting",
        "heart_kind_mixed": "resting or daily average",
        "activity_steps": (
            "Fewer steps than usual",
            "Daily steps ({days}-day mean): {recent} (N={n}) vs {base} ({bdays}-day median, N={bn})",
        ),
        "activity_workouts": (
            "No workouts",
            "No workouts in the last {days} days; there were {prev} in the previous 4 weeks",
        ),
        "bp_high": ("Blood pressure ≥140/90 repeated", "Readings ≥140/90 over {bp_days} days: {cnt} of {n}"),
        "bp_avg": ("Blood pressure above 130/80", "{bp_days}-day mean is {sys}/{dia} mmHg (N={n})"),
        "glucose_tir": (
            "Glucose: low time in range",
            "Time in 3.9–10.0 mmol/L: {tir}% over {days} days (readings: {n})",
        ),
        "glucose_tbr": (
            "Glucose: time below 3.9 mmol/L",
            "Below 3.9 mmol/L: {tbr}% of the time over {days} days (readings: {n})",
        ),
        "weight": (
            "Weight changed noticeably",
            "From {d0} ({v0} kg) to {d1} ({v1} kg): {delta} kg ({pct}%), first vs last measurement",
        ),
        "lab_high": ("{label} above range", "{value} {unit} ({date}), range up to {ref}"),
        "lab_low": ("{label} below range", "{value} {unit} ({date}), range from {ref}"),
        "lab_prev": " · previous {prev}",
        "labs_stale": ("Overdue lab tests: {n}", "Latest result is older than the recommended interval: {names}"),
    },
}

# next-best-action. Ключ — id правила или `lab:<canon>`/`lab_stale`. ПЛЕЙСХОЛДЕРЫ (см. шапку модуля).
ACTIONS = {
    "ru": {
        "sleep": "Обсудить режим сна с врачом, если так продолжается",
        "hrv": "Проверить нагрузку и восстановление; обсудить с врачом, если не проходит",
        "heart": "Проверить нагрузку, сон и самочувствие; обсудить с врачом, если не проходит",
        "activity_steps": "Проверить, не сбился ли режим движения",
        "activity_workouts": "Проверить, не сбился ли режим тренировок",
        "bp_high": "Обсудить повторяющиеся замеры давления с врачом",
        "bp_avg": "Обсудить показатели давления с врачом; продолжить измерения",
        "glucose_tir": "Обсудить показатели глюкозы с врачом",
        "glucose_tbr": "Обсудить показатели глюкозы с врачом",
        "weight": "Проверить, насколько изменение ожидаемо; обсудить с врачом при необходимости",
        "lab:LDL": "Обсудить результат с врачом; пересдать липидограмму через 8–12 недель",
        "lab:ApoB": "Обсудить результат с врачом; пересдать липидограмму через 8–12 недель",
        "lab:vitamin_D": "Уточнить у врача дозировку; пересдать через ~3 месяца",
        "lab:_default": "Обсудить результат с врачом; при необходимости пересдать",
        "lab_stale": "Пересдать просроченные анализы",
    },
    "en": {
        "sleep": "Discuss your sleep pattern with a doctor if this continues",
        "hrv": "Review training load and recovery; discuss with a doctor if it persists",
        "heart": "Review load, sleep and how you feel; discuss with a doctor if it persists",
        "activity_steps": "Check whether your movement routine slipped",
        "activity_workouts": "Check whether your training routine slipped",
        "bp_high": "Discuss the repeated blood pressure readings with a doctor",
        "bp_avg": "Discuss your blood pressure with a doctor; keep measuring",
        "glucose_tir": "Discuss your glucose readings with a doctor",
        "glucose_tbr": "Discuss your glucose readings with a doctor",
        "weight": "Check whether the change is expected; discuss with a doctor if needed",
        "lab:LDL": "Discuss the result with a doctor; retest the lipid panel in 8–12 weeks",
        "lab:ApoB": "Discuss the result with a doctor; retest the lipid panel in 8–12 weeks",
        "lab:vitamin_D": "Ask a doctor about dosing; retest in ~3 months",
        "lab:_default": "Discuss the result with a doctor; retest if needed",
        "lab_stale": "Retest the overdue lab tests",
    },
}

SUMMARY = {
    "ru": {
        "attention": "Обратить внимание: {streams}.",
        "labs_stale": "Просрочены анализы: {n}.",
        "calm": "Заметных отклонений от своей нормы за {days} дн. нет.",
        "no_data": "Недостаточно данных для сравнения.",
    },
    "en": {
        "attention": "Worth a look: {streams}.",
        "labs_stale": "Overdue lab tests: {n}.",
        "calm": "No notable deviations from your own norm over {days} days.",
        "no_data": "Not enough data for comparison.",
    },
}
