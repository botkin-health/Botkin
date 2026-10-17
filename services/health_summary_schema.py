"""Схема ответа GET /api/health/summary (вкладка «Состояние» миниаппа).

Контракт «нет потока»:
  * Поток, по которому у пользователя НЕТ ни одной строки за всё время (не подключён),
    в `streams` ОТСУТСТВУЕТ — ключа нет. Причина лежит в `data_gaps`
    (`reason="not_connected"`). Фронт рисует карточки только для ключей из `streams`.
  * Поток, по которому данные когда-то были, присутствует всегда, со `status`:
      ok            — данных достаточно, отклонений нет;
      attention     — есть пункт в `attention` по этому потоку;
      insufficient  — в окне меньше минимума точек: «мало данных (N=…)», в сравнениях не участвует;
      stale         — в окне данных нет вовсе, `latest` — последний старый факт, `stale_days`.
  * `streams` пуст и `onboarding=true` — если пользователя нет в БД.

Правила формата (CLAUDE.md «Правила аналитики»): `latest` — реальный замер с датой;
`avg`/`baseline` — всегда с `kind` (mean/median), `n` и подписью `label`.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

AttentionStream = Literal["sleep", "activity", "hrv", "heart", "weight", "bp", "glucose", "labs"]
StreamStatus = Literal["ok", "attention", "insufficient", "stale"]
Severity = Literal["high", "medium", "info"]


class Point(BaseModel):
    date: str
    value: Optional[float] = None
    value2: Optional[float] = None  # диастолическое для bp


class Latest(BaseModel):
    """Последний ФАКТ (реальный замер), не среднее."""

    value: Optional[float] = None
    value2: Optional[float] = None  # диастолическое для bp
    unit: str = ""
    date: str


class Aggregate(BaseModel):
    """Среднее/медиана по окну: всегда с видом агрегата, N и подписью."""

    value: Optional[float] = None
    value2: Optional[float] = None
    unit: str = ""
    kind: Literal["mean", "median"]
    n: int
    label: str
    window: Optional[str] = None  # "YYYY-MM-DD..YYYY-MM-DD"


class StreamCard(BaseModel):
    status: StreamStatus
    connected: bool = True
    last_date: Optional[str] = None
    stale_days: Optional[int] = None
    latest: Optional[Latest] = None
    avg: Optional[Aggregate] = None
    baseline: Optional[Aggregate] = None  # None, если N baseline < минимума (не сопоставимо)
    series: list[Point] = Field(default_factory=list)  # ровно window_days точек, value=null — нет данных
    extra: dict[str, Any] = Field(default_factory=dict)


class LabMarker(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    date: str
    days_ago: Optional[int] = None
    ref_low: Optional[float] = None  # None — нет референса для пола / пол не задан
    ref_high: Optional[float] = None
    flag: str = ""  # "↑" | "↓" | ""


class LabOutOfRange(LabMarker):
    direction: Literal["high", "low"]
    deviation_pct: int  # |значение − нарушенная граница| / граница × 100
    severity: Severity
    history: list[dict[str, Any]] = Field(default_factory=list)  # до 4 точек {date, value}, по возрастанию


class LabStale(BaseModel):
    key: str
    label: str
    days_ago: int
    threshold_days: int
    last_date: str


class LabsCard(BaseModel):
    status: StreamStatus
    connected: bool = True
    last_date: Optional[str] = None
    stale_days: Optional[int] = None
    last_test_date: Optional[str] = None
    n_markers: int = 0
    markers: list[LabMarker] = Field(default_factory=list)  # значения показываем всегда; флаги — только при явном поле
    out_of_range: list[LabOutOfRange] = Field(default_factory=list)
    stale: list[LabStale] = Field(default_factory=list)
    ref_note: Optional[str] = None


class Evidence(BaseModel):
    metric: str
    recent: Optional[dict[str, Any]] = None  # {value, kind, n, window}
    baseline: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AttentionItem(BaseModel):
    id: str
    stream: AttentionStream
    severity: Severity
    title: str
    detail: str
    evidence: Evidence
    action: Optional[str] = None  # next-best-action: плейсхолдер, утверждает врач
    data_date: Optional[str] = None


class DataGap(BaseModel):
    stream: str
    reason: Literal["not_connected", "insufficient", "stale", "sex_not_set"]
    hint_source: Optional[str] = None
    n: Optional[int] = None


class Links(BaseModel):
    dashboard_token_endpoint: str = "/api/dashboard_url"
    doctor_report_endpoint: str = "/api/doctor_report"


class HealthSummary(BaseModel):
    as_of: Optional[str] = None
    tz: Optional[str] = None
    window_days: int = 7
    lang: str = "ru"
    onboarding: bool = False
    sex: Optional[Literal["male", "female"]] = None  # только заданный явно; None → флаги анализов не ставим
    attention: list[AttentionItem] = Field(default_factory=list)
    summary_text: str = ""
    streams: dict[str, StreamCard | LabsCard] = Field(default_factory=dict)
    data_gaps: list[DataGap] = Field(default_factory=list)
    links: Links = Field(default_factory=Links)
