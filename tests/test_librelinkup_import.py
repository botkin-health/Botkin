"""Импортёр LibreLinkUp: парсинг измерений, конвертация единиц, дедуп (#96)."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pylibrelinkup.models.data import GlucoseMeasurement, GlucoseMeasurementWithTrend, Trend

# scripts/import/ — не пакет (import — ключевое слово), грузим по пути.
_MOD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "import" / "librelinkup.py"
_spec = importlib.util.spec_from_file_location("librelinkup_import", _MOD_PATH)
llu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llu)


def _gm(ts, mgdl):
    return GlucoseMeasurement(
        FactoryTimestamp=ts,
        Timestamp=ts,
        Type=1,
        ValueInMgPerDl=mgdl,
        MeasurementColor=1,
        GlucoseUnits=1,
        Value=mgdl / 18.0182,
        isHigh=False,
        isLow=False,
    )


def _gm_trend(ts, mgdl, trend):
    return GlucoseMeasurementWithTrend(
        FactoryTimestamp=ts,
        Timestamp=ts,
        Type=1,
        ValueInMgPerDl=mgdl,
        MeasurementColor=1,
        GlucoseUnits=1,
        Value=mgdl / 18.0182,
        isHigh=False,
        isLow=False,
        TrendArrow=trend,
    )


def test_mgdl_to_mmol():
    assert llu.mgdl_to_mmol(99.0) == 5.49
    assert llu.mgdl_to_mmol(180.182) == 10.0


def test_measurement_to_row_graph_has_no_trend():
    ts = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    row = llu.measurement_to_row(_gm(ts, 90.0))
    assert row["ts"] == ts
    assert row["value"] == 4.99
    assert row["trend"] is None
    assert row["raw"]["value_in_mg_per_dl"] == 90.0  # raw сериализуется для JSONB


def test_measurement_to_row_latest_has_trend():
    ts = datetime(2026, 6, 16, 12, 5, tzinfo=timezone.utc)
    row = llu.measurement_to_row(_gm_trend(ts, 108.0, Trend.STABLE))
    assert row["trend"] == 3  # STABLE
    assert row["value"] == 5.99


def test_dedupe_by_ts_collapses_and_sorts():
    ts1 = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 6, 16, 12, 5, tzinfo=timezone.utc)
    rows = [
        {"ts": ts2, "value": 6.0, "trend": None, "raw": {}},
        {"ts": ts1, "value": 5.0, "trend": None, "raw": {}},
        {"ts": ts2, "value": 6.5, "trend": 3, "raw": {}},  # дубль ts2 — побеждает последний
    ]
    out = llu.dedupe_by_ts(rows)
    assert [r["ts"] for r in out] == [ts1, ts2]
    assert out[1]["value"] == 6.5 and out[1]["trend"] == 3


class _FakePatient:
    def __init__(self, pid):
        self.patient_id = UUID(pid)


class _FakeClient:
    """Имитация PyLibreLinkUp: graph() + latest() пересекаются по ts (проверяем дедуп)."""

    def __init__(self, ts1, ts2):
        self._p = _FakePatient("999b0098-6ac0-11ee-89dc-f22a02593d8c")
        self._ts1, self._ts2 = ts1, ts2

    def get_patients(self):
        return [self._p]

    def graph(self, patient):
        return [_gm(self._ts1, 90.0), _gm(self._ts2, 100.0)]

    def latest(self, patient):
        return _gm_trend(self._ts2, 100.0, Trend.UP_SLOW)  # тот же ts2 → схлопнётся, но с трендом


def test_collect_rows_dedups_graph_and_latest():
    ts1 = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 6, 16, 12, 5, tzinfo=timezone.utc)
    result = llu.collect_rows(_FakeClient(ts1, ts2))

    assert list(result.keys()) == ["999b0098-6ac0-11ee-89dc-f22a02593d8c"]
    rows = result["999b0098-6ac0-11ee-89dc-f22a02593d8c"]
    assert len(rows) == 2  # ts2 из graph и latest схлопнулись
    assert rows[1]["trend"] == 4  # UP_SLOW от latest перезаписал graph-точку
