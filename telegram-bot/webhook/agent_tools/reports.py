"""Agent tools: rendered reports (doctor report, charts) the LLM hands back to the user."""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from webhook.jwt_auth import get_db, require_agent_scope
from bot_token import resolve_bot_token
from .common import _resolve_user_kb_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-reports"])


class RenderReportRequest(BaseModel):
    report_type: str = Field(
        "biomarker_dynamics",
        description=(
            "Тип отчёта: 'biomarker_dynamics' (общая панель 2×3) или "
            "'single_biomarker' (один маркер крупным планом, требует поле marker)."
        ),
    )
    marker: Optional[str] = Field(
        None,
        description="Имя биомаркера для single_biomarker. Принимает алиасы и русские названия.",
    )


@router.post("/render_report")
async def render_report(
    req: RenderReportRequest,
    user=Depends(require_agent_scope("rw")),
):
    """Сгенерировать PNG-инфографику и отправить юзеру в Telegram.

    Side-effect: вызывает sendPhoto через Bot API на user.telegram_id.
    Tool возвращает агенту короткий статус — агент дальше отвечает текстом
    («вот разбор, главное что вижу — ...»).

    Зачем не возвращать base64 / image-url агенту: Anthropic Messages API
    умеет принимать image на вход модели, но передать картинку дальше в
    Telegram всё равно надо отдельным вызовом. Проще, чтобы тул сам слал.
    """
    import requests as _requests
    from core.reports.biomarker_dynamics import (
        render_biomarker_dynamics_png,
        render_single_marker_png,
    )

    if req.report_type not in ("biomarker_dynamics", "single_biomarker"):
        return {
            "status": "error",
            "error": (f"unknown report_type '{req.report_type}'; supported: biomarker_dynamics, single_biomarker"),
        }

    kb_path, _source = _resolve_user_kb_path(user)
    if kb_path is None:
        return {"status": "error", "error": "kb-not-available", "sent": False}

    user_name = (user.first_name or "").strip()
    caption_suffix = ""
    try:
        if req.report_type == "single_biomarker":
            if not req.marker:
                return {
                    "status": "error",
                    "error": "missing-marker: для single_biomarker нужен параметр marker",
                    "sent": False,
                }
            result = render_single_marker_png(kb_path, req.marker, user_name=user_name)
            # render_single_marker_png может вернуть dict с ошибкой
            if isinstance(result, dict):
                return {"status": "error", "sent": False, **result}
            png_bytes = result
            caption_suffix = f" · {req.marker}"
        else:
            png_bytes = render_biomarker_dynamics_png(kb_path, user_name=user_name)
    except Exception as e:
        logger.error("render_report failed for %s: %s", user.telegram_id, e, exc_info=True)
        return {"status": "error", "error": f"render-failed: {e}", "sent": False}

    if not png_bytes:
        return {
            "status": "error",
            "error": "not-enough-data: нет биомаркеров с ≥2 наблюдениями",
            "sent": False,
        }

    bot_token = resolve_bot_token()
    if not bot_token:
        return {"status": "error", "error": "bot-token-missing", "sent": False}

    try:
        resp = _requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={
                "chat_id": user.telegram_id,
                "caption": (f"📊 Динамика биомаркеров{' · ' + user_name if user_name else ''}{caption_suffix}"),
            },
            files={"photo": ("biomarkers.png", png_bytes, "image/png")},
            timeout=20,
        )
        result = resp.json()
        if not result.get("ok"):
            logger.warning("sendPhoto failed: %s", result)
            return {"status": "error", "error": f"telegram: {result.get('description')}", "sent": False}
    except Exception as e:
        logger.error("sendPhoto exception for %s: %s", user.telegram_id, e, exc_info=True)
        return {"status": "error", "error": f"telegram-exception: {e}", "sent": False}

    return {
        "status": "ok",
        "sent": True,
        "report_type": req.report_type,
        "kb_source": kb_path.name,
        "telegram_message_id": result["result"].get("message_id"),
    }


@router.post("/doctor_report")
async def doctor_report(
    body: dict = Body(default={}),
    user=Depends(require_agent_scope("rw")),
    db=Depends(get_db),
):
    """Сгенерировать PDF-отчёт для врача (секции IPS) и отправить юзеру в чат.

    Side-effect: шлёт PDF Telegram-документом на user.telegram_id через общий
    helper send_doctor_report_to_chat (тот же путь, что у кнопки мини-аппа, #290/#291).
    body.language ('ru'|'en') задаёт язык отчёта (#300); иначе — ru.
    Агенту возвращаем короткий статус {status, sent} — дальше он отвечает текстом.
    """
    from services.doctor_report import send_doctor_report_to_chat
    from services.report_i18n import resolve_report_language

    lang = resolve_report_language((body or {}).get("language"), None)
    return send_doctor_report_to_chat(db, user.telegram_id, lang=lang)


class RenderChartRequest(BaseModel):
    """Универсальный рендер графика через публичный QuickChart.io.

    chart: Chart.js v4 JSON конфиг (как объект, не строка).
    caption: подпись к фото в Telegram (опционально).
    width / height: размеры в пикселях, по умолчанию mobile-friendly.
    """

    chart: dict = Field(..., description="Chart.js v4 config object")
    caption: Optional[str] = Field(None, description="Подпись к фото в Telegram")
    width: int = Field(600, ge=200, le=1600)
    height: int = Field(400, ge=200, le=1200)


_BOTKIN_PALETTE = [
    "#34c759",  # Botkin green (норма)
    "#ff9500",  # Botkin orange (внимание/выше нормы)
    "#007aff",  # Apple blue (нейтральный)
    "#5856d6",  # фиолет
    "#ff2d55",  # розово-красный
    "#5ac8fa",  # светло-голубой
]


def _enrich_chart_spec(chart: dict) -> dict:
    """Добавить визуальные defaults в минимальный spec.

    Агент шлёт `{type, data: {labels, datasets: [{label, data, yAxisID?}]}, options?}`,
    мы добиваем стиль (цвета, толщина, точки, заголовок, легенду, шрифт).
    Это режет output tokens агента примерно вдвое и заодно даёт единый
    Botkin-стиль на всех графиках.
    """
    if not isinstance(chart, dict):
        return chart
    chart = dict(chart)  # shallow copy чтобы не мутировать вход

    # Дефолты для каждого dataset
    data = chart.get("data") or {}
    datasets = data.get("datasets") or []
    chart_type = chart.get("type", "line")
    new_datasets = []
    for i, ds in enumerate(datasets):
        ds = dict(ds)
        color = _BOTKIN_PALETTE[i % len(_BOTKIN_PALETTE)]
        ds.setdefault("borderColor", color)
        if chart_type in ("line", "scatter"):
            ds.setdefault("backgroundColor", color + "26")  # ~15% alpha hex
            ds.setdefault("borderWidth", 2)
            ds.setdefault("pointRadius", 4)
            ds.setdefault("pointHoverRadius", 6)
            ds.setdefault("tension", 0.3)
            ds.setdefault("fill", False)
        elif chart_type in ("bar",):
            ds.setdefault("backgroundColor", color)
            ds.setdefault("borderWidth", 0)
        elif chart_type in ("doughnut", "pie", "polarArea"):
            # Для круговых каждый сегмент свой цвет — расширяем массив
            n = len(ds.get("data") or [])
            ds.setdefault(
                "backgroundColor",
                [_BOTKIN_PALETTE[k % len(_BOTKIN_PALETTE)] for k in range(n)],
            )
        new_datasets.append(ds)
    data["datasets"] = new_datasets
    chart["data"] = data

    # Дефолты options
    options = chart.get("options") or {}
    options.setdefault("responsive", False)
    options.setdefault("maintainAspectRatio", False)

    plugins = options.get("plugins") or {}
    plugins.setdefault(
        "legend",
        {"display": len(new_datasets) > 1, "position": "top", "labels": {"font": {"size": 13}}},
    )
    title_cfg = plugins.get("title") or {}
    if title_cfg.get("text"):
        title_cfg.setdefault("display", True)
        title_cfg.setdefault("font", {"size": 15, "weight": "bold"})
        title_cfg.setdefault("padding", {"bottom": 12})
        plugins["title"] = title_cfg
    options["plugins"] = plugins

    # Сетка побледнее, шрифт читаемее
    scales = options.get("scales") or {}
    for ax_id, ax in list(scales.items()):
        ax = dict(ax) if isinstance(ax, dict) else {}
        ax.setdefault("grid", {"color": "#e5e5ea", "lineWidth": 0.5})
        ax.setdefault("ticks", {"font": {"size": 11}})
        scales[ax_id] = ax
    if scales:
        options["scales"] = scales

    chart["options"] = options
    return chart


@router.post("/render_chart")
async def render_chart(
    req: RenderChartRequest,
    user=Depends(require_agent_scope("rw")),
):
    """Рендерит произвольный график через QuickChart.io и отправляет в Telegram.

    Side-effect: данные графика (числа, подписи, имя) уходят на сервер
    QuickChart Inc. для рендера. См. tradeoffs в обсуждении выбора. Если
    приватность критична — заменить URL на self-hosted instance.
    """
    import os
    import requests as _requests

    bot_token = resolve_bot_token()
    if not bot_token:
        return {"status": "error", "error": "bot-token-missing", "sent": False}

    # Добиваем минимальный spec нашими дефолтами (цвета, шрифты, легенда)
    enriched_chart = _enrich_chart_spec(req.chart)

    # 1. Рендер через QuickChart
    qc_url = os.getenv("QUICKCHART_URL", "https://quickchart.io/chart")
    try:
        qc_resp = _requests.post(
            qc_url,
            json={
                "chart": enriched_chart,
                "width": req.width,
                "height": req.height,
                "backgroundColor": "white",
                "format": "png",
                "version": "4",
            },
            timeout=15,
        )
    except Exception as e:
        logger.error("quickchart request failed for %s: %s", user.telegram_id, e)
        return {"status": "error", "error": f"quickchart-network: {e}", "sent": False}

    if not qc_resp.ok:
        # QuickChart возвращает текст ошибки в body — отдадим агенту чтобы он мог исправить spec
        err_body = qc_resp.text[:400]
        logger.warning("quickchart %s for user %s: %s", qc_resp.status_code, user.telegram_id, err_body)
        return {
            "status": "error",
            "error": f"quickchart-{qc_resp.status_code}",
            "details": err_body,
            "sent": False,
        }

    png_bytes = qc_resp.content
    if not png_bytes or len(png_bytes) < 200:
        return {"status": "error", "error": "quickchart-empty-response", "sent": False}

    # 2. sendPhoto в Telegram
    try:
        tg_resp = _requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={
                "chat_id": user.telegram_id,
                "caption": req.caption or "",
            },
            files={"photo": ("chart.png", png_bytes, "image/png")},
            timeout=20,
        )
        result = tg_resp.json()
        if not result.get("ok"):
            return {"status": "error", "error": f"telegram: {result.get('description')}", "sent": False}
    except Exception as e:
        logger.error("sendPhoto exception in render_chart for %s: %s", user.telegram_id, e, exc_info=True)
        return {"status": "error", "error": f"telegram-exception: {e}", "sent": False}

    return {
        "status": "ok",
        "sent": True,
        "telegram_message_id": result["result"].get("message_id"),
        "chart_size_bytes": len(png_bytes),
    }
