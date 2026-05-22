"""PNG-отчёт «Динамика биомаркеров» для BotkinClaw.

Берёт per-user knowledge_base.json, объединяет blood_tests / biochemistry /
hormones / vitamins, выбирает до 6 биомаркеров с максимальным числом
наблюдений по клиническому приоритету, рендерит 2×3 grid small-multiples:
линия + точки + полупрозрачная зона нормы.

Идея: вместо markdown-таблицы из 6×4 ячеек (которая в Telegram читается
плохо) — одна картинка с «врачебным» оформлением.

Используется через endpoint POST /api/agent/render_report?type=biomarker_dynamics.

ВАЖНО про формат имён маркеров: разные KB используют РАЗНЫЕ ключи для одной
и той же сущности. Например глюкоза может быть `glucose`, `glucose_mmol_L`,
`Glucose`. Поэтому каждый канонический маркер имеет список `aliases` всех
встречавшихся вариантов написания — `_collect_series` нормализует.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Каноничные маркеры с алиасами ─────────────────────────────────────────────
#
# `aliases` — все варианты ключей, встречавшихся в реальных KB.
# Если в новом юзере увидишь незнакомый ключ — добавь сюда.
#
# Reference ranges — взрослые мужчины, общая популяция.
MARKER_CONFIG = {
    "glucose": {
        "label": "Глюкоза",
        "unit": "ммоль/л",
        "ref_low": 3.9,
        "ref_high": 6.0,
        "aliases": ["glucose", "Glucose", "glucose_mmol_L"],
    },
    "hba1c": {
        "label": "HbA1c",
        "unit": "%",
        "ref_low": 4.0,
        "ref_high": 5.7,
        "aliases": ["HbA1c", "hba1c", "A1c", "a1c", "hba1c_pct"],
    },
    "hemoglobin": {
        "label": "Гемоглобин",
        "unit": "г/л",
        "ref_low": 130,
        "ref_high": 170,
        "aliases": ["Hb", "hemoglobin", "haemoglobin", "hemoglobin_g_L"],
    },
    "rbc": {
        "label": "Эритроциты",
        "unit": "×10¹²/л",
        "ref_low": 4.0,
        "ref_high": 5.5,
        "aliases": ["RBC", "rbc", "rbc_x10_12_L"],
    },
    "wbc": {
        "label": "Лейкоциты",
        "unit": "×10⁹/л",
        "ref_low": 4.0,
        "ref_high": 9.0,
        "aliases": ["WBC", "wbc", "wbc_x10_9_L"],
    },
    "hematocrit": {
        "label": "Гематокрит",
        "unit": "%",
        "ref_low": 39,
        "ref_high": 49,
        "aliases": ["Ht", "hematocrit", "hematocrit_pct", "haematocrit"],
    },
    "cholesterol_total": {
        "label": "Холестерин общий",
        "unit": "ммоль/л",
        "ref_low": 3.0,
        "ref_high": 5.2,
        "aliases": [
            "cholesterol_total",
            "total_cholesterol",
            "cholesterol",
            "cholesterol_mmol_L",
        ],
    },
    "ldl": {
        "label": "ЛПНП",
        "unit": "ммоль/л",
        "ref_low": 0,
        "ref_high": 3.0,
        "aliases": ["LDL", "ldl", "ldl_mmol_L"],
    },
    "hdl": {
        "label": "ЛПВП",
        "unit": "ммоль/л",
        "ref_low": 1.0,
        "ref_high": 2.5,
        "aliases": ["HDL", "hdl", "hdl_mmol_L"],
    },
    "triglycerides": {
        "label": "Триглицериды",
        "unit": "ммоль/л",
        "ref_low": 0,
        "ref_high": 1.7,
        "aliases": ["triglycerides", "TG", "tg", "triglycerides_mmol_L"],
    },
    "apob": {
        "label": "ApoB",
        "unit": "г/л",
        "ref_low": 0,
        "ref_high": 0.9,
        "aliases": ["ApoB", "apob", "apo_b", "apob_g_L"],
    },
    "alt": {
        "label": "АЛТ",
        "unit": "Ед/л",
        "ref_low": 0,
        "ref_high": 41,
        "aliases": ["ALT", "alt", "alt_U_L"],
    },
    "ast": {
        "label": "АСТ",
        "unit": "Ед/л",
        "ref_low": 0,
        "ref_high": 40,
        "aliases": ["AST", "ast", "ast_U_L"],
    },
    "creatinine": {
        "label": "Креатинин",
        "unit": "мкмоль/л",
        "ref_low": 64,
        "ref_high": 104,
        "aliases": ["creatinine", "Creatinine", "creatinine_umol_L"],
    },
    "bilirubin_total": {
        "label": "Билирубин",
        "unit": "мкмоль/л",
        "ref_low": 5,
        "ref_high": 21,
        "aliases": ["bilirubin_total", "total_bilirubin", "bilirubin_total_umol_L"],
    },
    "crp": {
        "label": "СРБ",
        "unit": "мг/л",
        "ref_low": 0,
        "ref_high": 5,
        "aliases": ["crp", "CRP", "hs_CRP", "hs-CRP", "hscrp", "crp_mg_L"],
    },
    "ferritin": {
        "label": "Ферритин",
        "unit": "нг/мл",
        "ref_low": 30,
        "ref_high": 300,
        "aliases": ["ferritin", "Ferritin", "ferritin_ng_mL"],
    },
    "psa": {
        "label": "ПСА",
        "unit": "нг/мл",
        "ref_low": 0,
        "ref_high": 4,
        "aliases": ["psa", "PSA", "PSA_total", "psa_ng_mL"],
    },
    "tsh": {
        "label": "ТТГ",
        "unit": "мМЕ/л",
        "ref_low": 0.4,
        "ref_high": 4.0,
        "aliases": ["TSH", "tsh", "tsh_mIU_L"],
    },
    "vitamin_d": {
        "label": "Витамин D",
        "unit": "нг/мл",
        "ref_low": 30,
        "ref_high": 100,
        "aliases": ["vitamin_d", "vitamin_D", "vitamin_D3", "vitD", "vit_d", "vitamin_d_ng_mL"],
    },
    "testosterone": {
        "label": "Тестостерон",
        "unit": "нмоль/л",
        "ref_low": 8.6,
        "ref_high": 29,
        "aliases": ["testosterone", "Testosterone", "total_testosterone"],
    },
    "iron": {
        "label": "Железо",
        "unit": "мкмоль/л",
        "ref_low": 10,
        "ref_high": 30,
        "aliases": ["iron", "Iron", "Fe", "iron_umol_L"],
    },
}

# Приоритет для отбора первых 6 панелей. Идея — то что чаще всего интересно
# при «разборе для врача»: метаболика + липиды + печень + одна функциональная.
PRIORITY_ORDER = [
    "ldl",
    "glucose",
    "hba1c",
    "cholesterol_total",
    "alt",
    "creatinine",
    "triglycerides",
    "hdl",
    "ferritin",
    "apob",
    "ast",
    "vitamin_d",
    "hemoglobin",
    "tsh",
    "testosterone",
    "crp",
    "bilirubin_total",
    "psa",
    "hematocrit",
    "rbc",
    "wbc",
    "iron",
]


def _build_alias_lookup() -> dict[str, str]:
    """Plain dict alias → canonical. Алиасы регистрозависимые — KB как есть."""
    out: dict[str, str] = {}
    for canonical, cfg in MARKER_CONFIG.items():
        for alias in cfg["aliases"]:
            out[alias] = canonical
    return out


_ALIAS_TO_CANON = _build_alias_lookup()


def _collect_series(kb: dict) -> dict[str, list[tuple[str, float]]]:
    """Собрать {canonical_marker: [(date_str, value), ...]} из всех релевантных секций KB."""
    series: dict[str, list[tuple[str, float]]] = {}
    for section in ("blood_tests", "biochemistry", "hormones", "vitamins", "tumor_markers"):
        for record in kb.get(section) or []:
            date_str = record.get("date")
            values = record.get("values") or {}
            if not date_str or not isinstance(values, dict):
                continue
            for key, val in values.items():
                canonical = _ALIAS_TO_CANON.get(key)
                if canonical is None:
                    continue
                # Игнорируем *_unit метаключи (там строка типа "%", "g/l")
                if isinstance(val, str):
                    continue
                try:
                    val_float = float(val)
                except (TypeError, ValueError):
                    continue
                series.setdefault(canonical, []).append((date_str, val_float))
    # Дедуп: один маркер может оказаться в blood_tests И в hormones за одну дату.
    # Берём среднее (или первое — на дисперсию между методиками сейчас не смотрим).
    deduped: dict[str, list[tuple[str, float]]] = {}
    for canonical, points in series.items():
        by_date: dict[str, list[float]] = {}
        for d, v in points:
            by_date.setdefault(d, []).append(v)
        deduped[canonical] = sorted(
            [(d, sum(vs) / len(vs)) for d, vs in by_date.items()],
            key=lambda p: p[0],
        )
    return deduped


def _pick_markers(series: dict[str, list], max_panels: int = 6) -> list[str]:
    """Выбрать до N маркеров по приоритету (среди тех, где ≥2 точки)."""
    candidates = [k for k in PRIORITY_ORDER if k in series and len(series[k]) >= 2]
    if len(candidates) < max_panels:
        extras = sorted(
            [k for k in series if k not in candidates and len(series[k]) >= 2],
            key=lambda k: -len(series[k]),
        )
        candidates += extras
    return candidates[:max_panels]


def resolve_marker_key(query: str) -> Optional[str]:
    """Разрешить произвольный пользовательский ключ к canonical маркеру.

    Принимает: канон ('glucose'), любой алиас ('LDL'), русское имя ('глюкоза'),
    общеупотребительные сокращения. Возвращает canonical key из MARKER_CONFIG
    или None если непонятно. Регистронезависимо.
    """
    if not query:
        return None
    q = query.strip().lower()

    # 1) Прямое совпадение с canonical key или label
    for canonical, cfg in MARKER_CONFIG.items():
        if q == canonical:
            return canonical
        if q == cfg["label"].lower():
            return canonical

    # 2) Совпадение с алиасом (любым регистром)
    for canonical, cfg in MARKER_CONFIG.items():
        for alias in cfg["aliases"]:
            if q == alias.lower():
                return canonical

    # 3) Русские/народные синонимы
    RU_SYNONYMS = {
        "витамин д": "vitamin_d",
        "витамин d": "vitamin_d",
        "vit d": "vitamin_d",
        "сахар": "glucose",
        "сахар крови": "glucose",
        "холестерин": "cholesterol_total",
        "общий холестерин": "cholesterol_total",
        "холестерин общий": "cholesterol_total",
        "лпнп": "ldl",
        "плохой холестерин": "ldl",
        "лпвп": "hdl",
        "хороший холестерин": "hdl",
        "триглицериды": "triglycerides",
        "тг": "triglycerides",
        "гемоглобин": "hemoglobin",
        "гликированный": "hba1c",
        "гликированный гемоглобин": "hba1c",
        "ферритин": "ferritin",
        "креатинин": "creatinine",
        "алт": "alt",
        "аст": "ast",
        "ттг": "tsh",
        "тестостерон": "testosterone",
        "псa": "psa",
        "пса": "psa",
        "срб": "crp",
        "билирубин": "bilirubin_total",
        "железо": "iron",
        "лейкоциты": "wbc",
        "эритроциты": "rbc",
        "гематокрит": "hematocrit",
    }
    if q in RU_SYNONYMS:
        return RU_SYNONYMS[q]
    return None


def render_single_marker_png(
    kb_path: Path | str,
    marker: str,
    user_name: str = "",
) -> Optional[bytes] | dict:
    """Большой график одного биомаркера.

    Возвращает PNG-байты ИЛИ dict с error/suggestions если маркер не распознан /
    нет данных. Это нужно чтобы агент мог осмысленно среагировать (предложить
    альтернативу) вместо «ой не получилось».
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    from matplotlib.ticker import MaxNLocator
    from matplotlib import rcParams

    rcParams["font.family"] = "DejaVu Sans"
    rcParams["axes.unicode_minus"] = False

    canonical = resolve_marker_key(marker)
    if canonical is None:
        return {
            "error": "unknown-marker",
            "query": marker,
            "available": sorted(MARKER_CONFIG.keys()),
        }

    kb = json.loads(Path(kb_path).read_text(encoding="utf-8"))
    series = _collect_series(kb)
    points = series.get(canonical) or []
    if len(points) < 2:
        # Возвращаем список того что есть — агент может предложить
        return {
            "error": "not-enough-points",
            "marker": canonical,
            "points_available": len(points),
            "markers_with_data": [k for k, v in series.items() if len(v) >= 2],
        }

    cfg = MARKER_CONFIG[canonical]
    dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in points]
    values = [v for _, v in points]
    ref_low = cfg["ref_low"]
    ref_high = cfg["ref_high"]

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=130)

    title = f"{cfg['label']} · {cfg['unit']}"
    if user_name:
        title += f"  ·  {user_name}"
    fig.suptitle(title, fontsize=15, fontweight="bold", y=0.97)

    ax.axhspan(ref_low, ref_high, color="#34c759", alpha=0.13, zorder=0, label="норма")

    colors = ["#34c759" if ref_low <= v <= ref_high else "#ff9500" for v in values]
    ax.plot(dates, values, color="#48484a", linewidth=2.0, zorder=1)
    ax.scatter(dates, values, c=colors, s=90, zorder=2, edgecolor="white", linewidth=1.5)

    # Подписи значений + дат
    span_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    for j, (d, v) in enumerate(zip(dates, values)):
        close_to_prev = j > 0 and (d - dates[j - 1]).days < max(120, span_days // 8)
        close_to_next = j < len(dates) - 1 and (dates[j + 1] - d).days < max(120, span_days // 8)
        if close_to_prev or close_to_next:
            y_off = 12 if j % 2 == 0 else -18
        else:
            y_off = 12
        ax.annotate(
            f"{v:g}",
            (d, v),
            textcoords="offset points",
            xytext=(0, y_off),
            ha="center",
            fontsize=11,
            fontweight="bold",
            color="#1c1c1e",
        )

    # Линии нормы (вверху/внизу)
    ax.axhline(ref_low, color="#34c759", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.axhline(ref_high, color="#34c759", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.text(
        dates[-1],
        ref_high,
        f"  верх нормы {ref_high}",
        fontsize=9,
        color="#34c759",
        va="bottom",
    )
    ax.text(
        dates[-1],
        ref_low,
        f"  низ нормы {ref_low}",
        fontsize=9,
        color="#34c759",
        va="top",
    )

    ax.tick_params(axis="x", labelsize=10, rotation=25)
    ax.tick_params(axis="y", labelsize=10)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    ax.grid(True, alpha=0.22, linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    y_lo = min(min(values), ref_low) * 0.85
    y_hi = max(max(values), ref_high) * 1.15
    if y_lo > 0 and min(values) > 0:
        ax.set_ylim(y_lo, y_hi)
    else:
        ax.set_ylim(min(0, min(values)) * 0.95, y_hi)

    # Дельта первая→последняя
    delta = values[-1] - values[0]
    delta_str = f"{delta:+g} {cfg['unit']}"
    period_str = f"{dates[0].strftime('%b %Y')} → {dates[-1].strftime('%b %Y')}"
    fig.text(
        0.5,
        0.02,
        f"{period_str}  ·  изменение: {delta_str}  ·  {len(points)} замеров",
        ha="center",
        fontsize=10,
        color="#6e6e72",
    )

    fig.tight_layout(rect=[0, 0.04, 1, 0.94])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def render_biomarker_dynamics_png(
    kb_path: Path | str,
    user_name: str = "",
) -> Optional[bytes]:
    """Сгенерировать PNG и вернуть байты. None если данных недостаточно."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    from matplotlib.ticker import MaxNLocator
    from matplotlib import rcParams

    rcParams["font.family"] = "DejaVu Sans"
    rcParams["axes.unicode_minus"] = False

    kb = json.loads(Path(kb_path).read_text(encoding="utf-8"))
    series = _collect_series(kb)
    markers = _pick_markers(series, max_panels=6)
    if not markers:
        logger.info("biomarker_dynamics: no markers with ≥2 points for %s", kb_path)
        return None

    rows, cols = 2, 3
    fig, axes = plt.subplots(rows, cols, figsize=(11, 6.5), dpi=130)
    axes = axes.flatten()

    title = "Динамика биомаркеров"
    if user_name:
        title += f" · {user_name}"
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    for i, ax in enumerate(axes):
        if i >= len(markers):
            ax.axis("off")
            continue
        canonical = markers[i]
        cfg = MARKER_CONFIG[canonical]
        points = series[canonical]
        dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in points]
        values = [v for _, v in points]

        ref_low = cfg["ref_low"]
        ref_high = cfg["ref_high"]
        ax.axhspan(ref_low, ref_high, color="#34c759", alpha=0.12, zorder=0)

        colors = ["#34c759" if ref_low <= v <= ref_high else "#ff9500" for v in values]
        ax.plot(dates, values, color="#48484a", linewidth=1.5, zorder=1)
        ax.scatter(dates, values, c=colors, s=42, zorder=2, edgecolor="white", linewidth=1.2)

        # Подписи значений: чередуем верх/низ когда точки кучные, чтобы не накладывались.
        # Считаем «кучными» соседние с расстоянием <120 дней.
        span_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
        for j, (d, v) in enumerate(zip(dates, values)):
            close_to_prev = j > 0 and (d - dates[j - 1]).days < max(120, span_days // 8)
            close_to_next = j < len(dates) - 1 and (dates[j + 1] - d).days < max(120, span_days // 8)
            if close_to_prev or close_to_next:
                y_off = 8 if j % 2 == 0 else -13
            else:
                y_off = 8
            ax.annotate(
                f"{v:g}",
                (d, v),
                textcoords="offset points",
                xytext=(0, y_off),
                ha="center",
                fontsize=8,
                color="#1c1c1e",
            )

        ax.set_title(f"{cfg['label']} · {cfg['unit']}", fontsize=10, fontweight="bold")
        ax.tick_params(axis="x", labelsize=8, rotation=30)
        ax.tick_params(axis="y", labelsize=8)
        # Не больше 5 тиков по X — иначе на коротких периодах появляются дубли «Jan 2023».
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
        ax.grid(True, alpha=0.18, linewidth=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        y_lo = min(min(values), ref_low) * 0.92
        y_hi = max(max(values), ref_high) * 1.10
        # На случай ref_low=0 и значения у нуля — не уйти в отрицательную ось
        if y_lo > 0 and min(values) > 0:
            ax.set_ylim(y_lo, y_hi)
        else:
            ax.set_ylim(min(0, min(values)) * 0.95, y_hi)

    fig.text(
        0.5,
        0.01,
        "Зелёная зона — референсный диапазон. Жёлтая точка — вне нормы.",
        ha="center",
        fontsize=8.5,
        color="#6e6e72",
    )
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
