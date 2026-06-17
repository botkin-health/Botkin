"""Импортёр LibreLinkUp: парсинг измерений, конвертация единиц, дедуп, on-demand refresh (#96, #129)."""

import importlib.util
import json
import types
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pylibrelinkup.models.data import GlucoseMeasurement, GlucoseMeasurementWithTrend, Trend

# scripts/import/ — не пакет (import — ключевое слово), грузим по пути.
_MOD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "import" / "librelinkup.py"
_spec = importlib.util.spec_from_file_location("librelinkup_import", _MOD_PATH)
llu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llu)


def _gm(factory, mgdl, local=None):
    # factory = UTC (хранится в ts); local = наивное локальное (в ts попадать НЕ должно).
    return GlucoseMeasurement(
        FactoryTimestamp=factory,
        Timestamp=local or factory,
        Type=1,
        ValueInMgPerDl=mgdl,
        MeasurementColor=1,
        GlucoseUnits=1,
        Value=mgdl / 18.0182,
        isHigh=False,
        isLow=False,
    )


def _gm_trend(factory, mgdl, trend, local=None):
    return GlucoseMeasurementWithTrend(
        FactoryTimestamp=factory,
        Timestamp=local or factory,
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


def test_ts_uses_factory_timestamp_not_local():
    """Регресс #129: ts = factory_timestamp (UTC, tz-aware), а НЕ наивное локальное .timestamp."""
    factory = datetime(2026, 6, 16, 21, 50, tzinfo=timezone.utc)  # UTC
    local = datetime(2026, 6, 17, 0, 50)  # наивное МСК (+3) — не должно попасть в ts
    row = llu.measurement_to_row(_gm(factory, 99.0, local=local))
    assert row["ts"] == factory
    assert row["ts"].tzinfo is not None  # tz-aware → корректно ляжет в timestamptz
    assert row["raw"]["timestamp_local"].startswith("2026-06-17T00:50")
    assert row["raw"]["factory_timestamp"].startswith("2026-06-16T21:50")


# ── on-demand refresh (#129) ──────────────────────────────────────────────────

_PID = "999b0098-6ac0-11ee-89dc-f22a02593d8c"


class _FakeCursor:
    def __init__(self, pid):
        self._pid = pid
        self._last = ""
        self.inserts = 0

    def execute(self, sql, params=None):
        self._last = sql
        if "INSERT INTO glucose_readings" in sql:
            self.inserts += 1

    def fetchone(self):
        if "SELECT patient_id" in self._last:
            return (self._pid,) if self._pid else None
        if "INSERT INTO glucose_readings" in self._last:
            return (True,)  # was_inserted
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def close(self):
        pass


def test_refresh_no_mapping_skips_network(monkeypatch):
    cur = _FakeCursor(None)  # SELECT patient_id → None (юзер не привязан)
    monkeypatch.setattr(llu, "psycopg2", types.SimpleNamespace(connect=lambda url: _FakeConn(cur)))
    called = []
    monkeypatch.setattr(llu, "get_cached_client", lambda reset=False: called.append(1))

    n = llu.refresh_glucose_for_telegram(999, db_url="postgresql://x")
    assert n == 0
    assert not called  # без привязки в сеть не ходим


def test_refresh_with_mapping_upserts(monkeypatch):
    cur = _FakeCursor(_PID)
    monkeypatch.setattr(llu, "psycopg2", types.SimpleNamespace(connect=lambda url: _FakeConn(cur)))
    ts1 = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 6, 16, 12, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(llu, "get_cached_client", lambda reset=False: _FakeClient(ts1, ts2))

    n = llu.refresh_glucose_for_telegram(895655, db_url="postgresql://x")
    assert n == 2  # 2 дедуп-точки апсертнуты
    assert cur.inserts == 2


# ── персист/переиспользование токена (#135) ──────────────────────────────────


class _FakeAuthClient:
    token = None
    account_id_hash = None

    def __init__(self):
        self.auth_calls = 0

    def _set_token(self, t):
        self.token = t

    def _set_account_id_hash(self, h):
        self.account_id_hash = h

    def authenticate(self):
        self.auth_calls += 1
        self.token = "FRESH"
        self.account_id_hash = "FRESH_HASH"


def test_get_cached_client_restores_token_without_login(monkeypatch, tmp_path):
    tok = tmp_path / "llu_token.json"
    tok.write_text(json.dumps({"token": "T", "account_id_hash": "H"}))
    monkeypatch.setattr(llu, "TOKEN_CACHE", tok)
    monkeypatch.setattr(llu, "_cached_client", None)
    fake = _FakeAuthClient()
    monkeypatch.setattr(llu, "_new_client", lambda: fake)

    c = llu.get_cached_client()
    assert c.token == "T"  # восстановлен с диска
    assert fake.auth_calls == 0  # НЕ логинились


def test_get_client_persists_token(monkeypatch, tmp_path):
    tok = tmp_path / "llu_token.json"
    monkeypatch.setattr(llu, "TOKEN_CACHE", tok)
    monkeypatch.setattr(llu, "_new_client", lambda: _FakeAuthClient())

    llu.get_client()
    assert json.loads(tok.read_text()) == {"token": "FRESH", "account_id_hash": "FRESH_HASH"}


def test_reset_drops_saved_token(monkeypatch, tmp_path):
    tok = tmp_path / "llu_token.json"
    tok.write_text(json.dumps({"token": "OLD", "account_id_hash": "H"}))
    monkeypatch.setattr(llu, "TOKEN_CACHE", tok)
    monkeypatch.setattr(llu, "_cached_client", None)
    monkeypatch.setattr(llu, "_new_client", lambda: _FakeAuthClient())

    c = llu.get_cached_client(reset=True)  # выкинуть протухший токен → свежий логин
    assert not tok.exists() or json.loads(tok.read_text())["token"] == "FRESH"
    assert c.token == "FRESH"


def test_fetch_patient_ids(monkeypatch):
    class _P:
        def __init__(self, pid):
            self.patient_id = pid

    class _C:
        def get_patients(self):
            return [_P("a"), _P("b")]

    monkeypatch.setattr(llu, "get_cached_client", lambda reset=False: _C())
    assert llu.fetch_patient_ids() == ["a", "b"]
