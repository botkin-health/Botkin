"""Agent tools: blood pressure, body composition, weight history."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db, require_agent_scope
from .common import _dt_isoformat_local

router = APIRouter(prefix="/api/agent", tags=["agent-tools-vitals"])


class LogBPRequest(BaseModel):
    systolic: int = Field(..., ge=50, le=300, description="Systolic pressure mmHg")
    diastolic: int = Field(..., ge=30, le=200, description="Diastolic pressure mmHg")
    pulse: Optional[int] = Field(None, ge=30, le=250, description="Pulse bpm")
    measured_at: Optional[str] = None  # ISO datetime; defaults to now


EARLIEST_PLAUSIBLE_MEASUREMENT = datetime(2000, 1, 1, tzinfo=timezone.utc)


FUTURE_MEASUREMENT_TOLERANCE = timedelta(days=1)


class BodyCompositionMeasurement(BaseModel):
    """Один замер с умных весов. Границы — санити-чек на ошибку единиц измерения."""

    measured_at: str = Field(..., description="ISO datetime замера (реальное время с весов)")
    weight: float = Field(..., gt=20, le=400, description="Вес, кг")
    body_fat: Optional[float] = Field(None, ge=0, le=100, description="Жир, %")
    muscle_mass: Optional[float] = Field(None, ge=0, le=200, description="Мышечная масса, кг")
    water: Optional[float] = Field(None, ge=0, le=100, description="Вода, %")
    bone_mass: Optional[float] = Field(None, ge=0, le=50, description="Костная масса, кг")
    visceral_fat: Optional[float] = Field(None, ge=0, le=60, description="Висцеральный жир (индекс)")
    bmi: Optional[float] = Field(None, gt=5, le=100, description="ИМТ")
    # Весы Withings мерят пульс при взвешивании (стоя, натощак — по сути пульс покоя).
    heart_rate: Optional[int] = Field(None, ge=20, le=250, description="Пульс при взвешивании, уд/мин")
    bmr_kcal: Optional[int] = Field(None, ge=500, le=6000, description="Основной обмен по составу тела, ккал")
    fat_mass_kg: Optional[float] = Field(None, ge=0, le=200, description="Жировая масса, кг")
    lean_mass_kg: Optional[float] = Field(None, ge=0, le=200, description="Безжировая масса, кг")


def bmi_from_height(weight_kg: float, height_cm: float | None) -> float | None:
    """ИМТ из веса и роста профиля. None, если роста нет или он неправдоподобен.

    Весы Withings ИМТ не присылают вовсе (в measuregrps его нет), а рост они и не
    знают — он есть только в профиле пользователя. Поэтому считаем на сервере:
    так значение появится у любого канала, который прислал вес без ИМТ.
    """
    # isinstance, а не просто truthiness: в профиле может лежать что угодно
    # (или мок в тестах), а сравнение с не-числом роняет весь запрос.
    if not isinstance(height_cm, (int, float)) or isinstance(height_cm, bool):
        return None
    if not (100 <= height_cm <= 250):
        return None
    return round(weight_kg / (height_cm / 100) ** 2, 1)


class LogBodyCompositionRequest(BaseModel):
    measurements: list[BodyCompositionMeasurement] = Field(
        ..., min_length=1, max_length=500, description="Батч замеров (импорт истории — одним запросом)"
    )
    source: str = Field(
        "agent_api",
        pattern=r"^[a-z0-9_]{1,50}$",
        description="Канал данных: withings / zepp / hae / agent_api",
    )


@router.post("/log_bp")
async def log_bp(
    req: LogBPRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Save a blood pressure reading to blood_pressure_logs."""
    from sqlalchemy import text as _text

    # Parse measured_at
    if req.measured_at:
        try:
            measured_at = datetime.fromisoformat(req.measured_at)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid measured_at: {req.measured_at!r}. Use ISO datetime.")
    else:
        measured_at = datetime.now(timezone.utc)

    db.execute(
        _text(
            """INSERT INTO blood_pressure_logs
               (user_id, measured_at, systolic, diastolic, heart_rate, source)
               VALUES (:uid, :ts, :sys, :dia, :hr, 'agent_api')
               ON CONFLICT (user_id, measured_at) DO UPDATE
                 SET systolic = EXCLUDED.systolic,
                     diastolic = EXCLUDED.diastolic,
                     heart_rate = COALESCE(EXCLUDED.heart_rate, blood_pressure_logs.heart_rate)"""
        ),
        {
            "uid": user.telegram_id,
            "ts": measured_at,
            "sys": req.systolic,
            "dia": req.diastolic,
            "hr": req.pulse,
        },
    )
    db.commit()

    return {
        "status": "ok",
        "measured_at": _dt_isoformat_local(measured_at, user),
        "systolic": req.systolic,
        "diastolic": req.diastolic,
        "pulse": req.pulse,
    }


@router.post("/log_body_composition")
async def log_body_composition(
    req: LogBodyCompositionRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Записать замеры состава тела с внешних умных весов в `weights`.

    Зачем отдельный канал: в HealthKit нет типов для мышечной массы, воды, костной
    массы и висцерального жира — через Apple Health / HAE доходят только вес, % жира
    и безжировая масса. Полный состав приходит либо от Withings/Zepp напрямую, либо
    исторически заливался с мака владельца через ssh + psql суперюзером
    (`scripts/import/zepp_csv.py`), что требовало доступа к прод-серверу.

    Этот эндпоинт закрывает ту же задачу по HTTPS с PAT-токеном: `user_id` берётся
    из токена (не из тела запроса), RLS изолирует данные, доступ к серверу и
    суперюзер Postgres не нужны.

    Батч атомарен: все таймстампы валидируются до первой записи, поэтому битый замер
    не оставляет половину истории записанной. Повторный `measured_at` внутри одного
    батча — не ошибка, применяется последний (см. flush в upsert_device_weight).

    `measured_at` обязан нести часовой пояс — ключ идемпотентности должен означать
    один и тот же момент независимо от того, как клиент его сериализовал.
    """
    from database.crud import MANUAL_WEIGHT_SOURCES, upsert_device_weight

    # Ручные источники дедупятся по календарному дню в upsert_manual_weight (#170).
    # Если пустить device-замеры под таким source, ручной апсерт потом подменит
    # реальный замер с весов — каналы должны остаться различимыми.
    if req.source in MANUAL_WEIGHT_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source={req.source!r} зарезервирован за ручным вводом. Используйте имя канала (withings, zepp, hae).",
        )

    now = datetime.now(timezone.utc)
    parsed = []
    for m in req.measurements:
        try:
            measured_at = datetime.fromisoformat(m.measured_at)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid measured_at: {m.measured_at!r}. Use ISO datetime with UTC offset.",
            )

        # Требуем явный офсет: эндпоинт нужен для ИДЕМПОТЕНТНОГО импорта, а ключ
        # идемпотентности — measured_at. Naive-строка на Postgres трактуется по
        # session TimeZone (нигде не зафиксирован), поэтому один и тот же момент,
        # присланный то с офсетом то без, дал бы два ряда вместо одного.
        if measured_at.tzinfo is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"measured_at={m.measured_at!r} без часового пояса. "
                    "Укажите офсет явно (например 2026-08-01T07:00:00+03:00 или ...Z)."
                ),
            )
        measured_at = measured_at.astimezone(timezone.utc)

        # Санити-границы: мусорная дата молча перекосила бы агрегаты дашборда и phenoage
        if measured_at < EARLIEST_PLAUSIBLE_MEASUREMENT or measured_at > now + FUTURE_MEASUREMENT_TOLERANCE:
            raise HTTPException(
                status_code=422,
                detail=f"measured_at={m.measured_at!r} вне правдоподобного диапазона замеров.",
            )

        parsed.append((measured_at, m))

    inserted = 0
    updated = 0
    for measured_at, m in parsed:
        created = upsert_device_weight(
            db,
            user_id=user.telegram_id,
            measured_at=measured_at,
            weight=m.weight,
            body_fat=m.body_fat,
            muscle_mass=m.muscle_mass,
            water=m.water,
            # ИМТ считаем сами, если канал его не прислал: рост знает только профиль.
            bmi=m.bmi if m.bmi is not None else bmi_from_height(m.weight, getattr(user, "height_cm", None)),
            # Колонка visceral_fat — INTEGER, весы отдают float
            visceral_fat=round(m.visceral_fat) if m.visceral_fat is not None else None,
            bone_mass=m.bone_mass,
            heart_rate=m.heart_rate,
            bmr_kcal=m.bmr_kcal,
            fat_mass_kg=m.fat_mass_kg,
            lean_mass_kg=m.lean_mass_kg,
            source=req.source,
        )
        if created:
            inserted += 1
        else:
            updated += 1
    db.commit()

    return {
        "status": "ok",
        "inserted": inserted,
        "updated": updated,
        "source": req.source,
    }


@router.get("/recent_bp")
async def recent_bp(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent blood-pressure measurements (last `days`).

    Returns each row with measured_at, systolic, diastolic, pulse, source.
    Plus simple aggregates: mean/min/max systolic+diastolic, latest pulse,
    pct of measurements above 140/90 (Stage 1 hypertension threshold).
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 90))
    sql = sql_text(
        """
        SELECT measured_at, systolic, diastolic, heart_rate, source
        FROM blood_pressure_logs
        WHERE user_id = :uid
          AND measured_at >= NOW() - (:days || ' days')::interval
        ORDER BY measured_at DESC
        LIMIT 200
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "measured_at": _dt_isoformat_local(r.measured_at, user),
            "systolic": r.systolic,
            "diastolic": r.diastolic,
            "pulse": r.heart_rate,
            "source": r.source,
        }
        for r in rows
    ]

    if not items:
        return {"status": "ok", "period_days": days, "count": 0, "items": []}

    sys_vals = [i["systolic"] for i in items]
    dia_vals = [i["diastolic"] for i in items]
    above_threshold = sum(1 for i in items if i["systolic"] >= 140 or i["diastolic"] >= 90)

    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "stats": {
            "systolic": {"avg": round(sum(sys_vals) / len(sys_vals), 1), "min": min(sys_vals), "max": max(sys_vals)},
            "diastolic": {"avg": round(sum(dia_vals) / len(dia_vals), 1), "min": min(dia_vals), "max": max(dia_vals)},
            "stage1_pct": round(100 * above_threshold / len(items), 1),
        },
        "items": items[:30],  # cap for token budget
    }


@router.get("/weight_history")
async def weight_history(
    days: Optional[int] = None,
    series: bool = False,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """История веса и состава тела (жир/мышцы/висцеральный жир).

    Источник: `weights` table — пишется HAE (Apple Health → Mi-весы), Zepp Life,
    Apple Health XML импортом. История с 2015 у долгих пользователей.

    Параметры:
    - `days`: окно в днях (7-365). Без него — только all-time агрегат.
    - `series`: True — добавить в ответ поле `points` со ВСЕМИ замерами в окне
      (по одному на дату, среднее если в день несколько источников). Нужно
      когда собираешься рисовать график через render_chart. Дефолт False —
      для текстовых вопросов хватает агрегатов, чтобы не раздувать ответ.

    Поля extremes: запись со значением + дата. body_fat фильтруется > 5
    (нулевые значения = весы не смогли измерить, мусор).
    """
    from sqlalchemy import text as sql_text

    in_window = max(7, min(days, 365)) if days else None

    def _to_date_str(ts) -> Optional[str]:
        """Накласть .date().isoformat() на datetime, или вернуть str иначе.

        SQLAlchemy в SQLite (тесты) возвращает datetime, в Postgres — тоже.
        Старое SQL `measured_at::date AS date` ломалось на SQLite, поэтому теперь
        конвертация в Python.
        """
        if ts is None:
            return None
        if hasattr(ts, "date"):
            return ts.date().isoformat()
        return str(ts)[:10]

    # Latest weighing — current state, most useful single fact
    latest_row = db.execute(
        sql_text(
            """
            SELECT measured_at, weight, body_fat, muscle_mass,
                   visceral_fat, bmi, source
            FROM weights
            WHERE user_id = :uid
            ORDER BY measured_at DESC
            LIMIT 1
            """
        ),
        {"uid": user.telegram_id},
    ).fetchone()

    if not latest_row:
        return {"status": "no_data", "count": 0}

    latest = {
        "date": _to_date_str(latest_row.measured_at),
        "weight_kg": round(latest_row.weight, 1),
        "body_fat_pct": round(latest_row.body_fat, 1) if latest_row.body_fat else None,
        "muscle_mass_kg": round(latest_row.muscle_mass, 1) if latest_row.muscle_mass else None,
        "visceral_fat": latest_row.visceral_fat,
        "bmi": round(latest_row.bmi, 1) if latest_row.bmi else None,
        "source": latest_row.source,
    }

    def _extremes(where_clause: str, params: dict) -> dict:
        # Min/max weight (ignores body_fat NULL)
        w_min = db.execute(
            sql_text(
                f"SELECT measured_at, weight FROM weights "
                f"WHERE user_id = :uid {where_clause} ORDER BY weight ASC LIMIT 1"
            ),
            params,
        ).fetchone()
        w_max = db.execute(
            sql_text(
                f"SELECT measured_at, weight FROM weights "
                f"WHERE user_id = :uid {where_clause} ORDER BY weight DESC LIMIT 1"
            ),
            params,
        ).fetchone()
        # Min/max body_fat (filter > 5 — нулевые значения = весы не измерили)
        bf_min = db.execute(
            sql_text(
                f"SELECT measured_at, body_fat, weight FROM weights "
                f"WHERE user_id = :uid AND body_fat > 5 {where_clause} "
                f"ORDER BY body_fat ASC LIMIT 1"
            ),
            params,
        ).fetchone()
        bf_max = db.execute(
            sql_text(
                f"SELECT measured_at, body_fat, weight FROM weights "
                f"WHERE user_id = :uid AND body_fat > 5 {where_clause} "
                f"ORDER BY body_fat DESC LIMIT 1"
            ),
            params,
        ).fetchone()
        # Counts + date range
        meta = db.execute(
            sql_text(
                f"SELECT COUNT(*) AS n, MIN(measured_at) AS first, "
                f"MAX(measured_at) AS last FROM weights "
                f"WHERE user_id = :uid {where_clause}"
            ),
            params,
        ).fetchone()

        return {
            "count": meta.n,
            "first_date": _to_date_str(meta.first),
            "last_date": _to_date_str(meta.last),
            "min_weight": {"date": _to_date_str(w_min.measured_at), "weight_kg": round(w_min.weight, 1)}
            if w_min
            else None,
            "max_weight": {"date": _to_date_str(w_max.measured_at), "weight_kg": round(w_max.weight, 1)}
            if w_max
            else None,
            "min_body_fat": {
                "date": _to_date_str(bf_min.measured_at),
                "body_fat_pct": round(bf_min.body_fat, 1),
                "weight_kg": round(bf_min.weight, 1),
            }
            if bf_min
            else None,
            "max_body_fat": {
                "date": _to_date_str(bf_max.measured_at),
                "body_fat_pct": round(bf_max.body_fat, 1),
                "weight_kg": round(bf_max.weight, 1),
            }
            if bf_max
            else None,
        }

    result: dict[str, Any] = {
        "status": "ok",
        "latest": latest,
        "all_time": _extremes("", {"uid": user.telegram_id}),
    }

    if in_window:
        # Python-computed cutoff — works одинаково на Postgres и SQLite (тесты)
        cutoff = datetime.now(timezone.utc) - timedelta(days=in_window)
        result["window_days"] = in_window
        result["in_window"] = _extremes(
            "AND measured_at >= :cutoff",
            {"uid": user.telegram_id, "cutoff": cutoff},
        )

    # Полный ряд точек — для рисования графика. Дедуп по дате: среднее когда
    # за день несколько источников (apple_health_v2 + zepp_life дают одно и
    # то же значение, или почти).
    if series:
        if in_window:
            cutoff = datetime.now(timezone.utc) - timedelta(days=in_window)
            rows = db.execute(
                sql_text(
                    """
                    SELECT measured_at, weight, body_fat
                    FROM weights
                    WHERE user_id = :uid AND measured_at >= :cutoff
                    ORDER BY measured_at ASC
                    """
                ),
                {"uid": user.telegram_id, "cutoff": cutoff},
            ).fetchall()
        else:
            rows = db.execute(
                sql_text(
                    """
                    SELECT measured_at, weight, body_fat
                    FROM weights
                    WHERE user_id = :uid
                    ORDER BY measured_at ASC
                    """
                ),
                {"uid": user.telegram_id},
            ).fetchall()

        # Группируем по дате, усредняем (несколько источников → одна точка)
        from collections import defaultdict

        per_day: dict[str, dict] = defaultdict(lambda: {"weights": [], "body_fats": []})
        for r in rows:
            day = _to_date_str(r.measured_at)
            per_day[day]["weights"].append(r.weight)
            if r.body_fat and r.body_fat > 5:  # см. фильтр для extremes
                per_day[day]["body_fats"].append(r.body_fat)

        points = []
        for day in sorted(per_day.keys()):
            ws = per_day[day]["weights"]
            bfs = per_day[day]["body_fats"]
            points.append(
                {
                    "date": day,
                    "weight_kg": round(sum(ws) / len(ws), 2),
                    "body_fat_pct": round(sum(bfs) / len(bfs), 1) if bfs else None,
                }
            )
        result["points"] = points
        result["points_count"] = len(points)

    return result


@router.get("/body_measurements")
async def body_measurements(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Антропометрия: талия, шея, бёдра, грудь, бедро, бицепс (см), сила хвата (кг).

    Источник: `body_measurements` table — ручной ввод пользователя через бот/админку.
    Талия — важная метрика метаболического здоровья (waist circumference > BMI
    по предсказанию ССЗ-риска, особенно для visceral fat). Сила хвата (grip_right_kg/
    grip_left_kg, ручной динамометр) — маркер саркопении/функциональной силы.

    Возвращает latest замер, all-time min/max каждой метрики с датами, и
    тренд waist (last 6 measurements) — самая клинически релевантная.
    """
    from sqlalchemy import text as sql_text

    rows = db.execute(
        sql_text(
            """
            SELECT date, waist_cm, neck_cm, hips_cm, chest_cm, thigh_cm, biceps_cm,
                   grip_right_kg, grip_left_kg, notes
            FROM body_measurements
            WHERE user_id = :uid
            ORDER BY date DESC
            """
        ),
        {"uid": user.telegram_id},
    ).fetchall()

    if not rows:
        return {"status": "no_data", "count": 0, "reason": "no body_measurements entries"}

    latest = rows[0]
    metrics = ["waist_cm", "neck_cm", "hips_cm", "chest_cm", "thigh_cm", "biceps_cm", "grip_right_kg", "grip_left_kg"]

    def _extremes(metric: str) -> dict | None:
        vals = [(r.date, getattr(r, metric)) for r in rows if getattr(r, metric) is not None]
        if not vals:
            return None
        min_v = min(vals, key=lambda x: x[1])
        max_v = max(vals, key=lambda x: x[1])
        return {
            "min": {"date": min_v[0].isoformat(), "value": round(min_v[1], 1)},
            "max": {"date": max_v[0].isoformat(), "value": round(max_v[1], 1)},
            "current": round(getattr(latest, metric), 1) if getattr(latest, metric) is not None else None,
            "count": len(vals),
        }

    # Waist trend — last 6 measurements (for ratio/direction)
    waist_trend = [
        {"date": r.date.isoformat(), "waist_cm": round(r.waist_cm, 1)} for r in rows[:6] if r.waist_cm is not None
    ]

    return {
        "status": "ok",
        "count": len(rows),
        "latest": {
            "date": latest.date.isoformat(),
            **{m: round(getattr(latest, m), 1) if getattr(latest, m) is not None else None for m in metrics},
            "notes": latest.notes,
        },
        "extremes": {m: _extremes(m) for m in metrics},
        "waist_trend_last_6": waist_trend,
    }
