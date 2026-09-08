"""Agent tools: onboarding questionnaire, user settings, user profile summary."""

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db, require_agent_scope

router = APIRouter(prefix="/api/agent", tags=["agent-tools-profile"])


class UpdateUserSettingsRequest(BaseModel):
    """Все поля опциональны — обновляем только те что переданы."""

    target_weight_kg: Optional[float] = Field(None, ge=30, le=300)
    target_weight_date: Optional[str] = None  # YYYY-MM-DD
    calorie_goal_pct: Optional[int] = Field(None, ge=-50, le=50, description="Дефицит/профицит %, -15 = -15%")
    bmr_override: Optional[int] = Field(None, ge=500, le=5000)
    bmr_source: Optional[str] = Field(None, pattern="^(auto|override|fixed)$")
    activity_level: Optional[str] = None
    show_calorie_budget_bar: Optional[bool] = None
    supplement_reminders_enabled: Optional[bool] = None
    supplement_reminder_time: Optional[str] = None  # HH:MM
    supplements: Optional[list] = Field(
        None,
        description="Полный список добавок (заменит существующий). Каждая: {name, dose?, slot?}. Slots: morning_before, morning_with, evening.",
    )


class UpdateProfileRequest(BaseModel):
    """Анкетные поля из users — все опциональны."""

    sex: Optional[str] = Field(None, pattern="^(male|female|other)$")
    height_cm: Optional[int] = Field(None, ge=100, le=250)
    birth_date: Optional[str] = None  # YYYY-MM-DD
    timezone: Optional[str] = None
    smoking_status: Optional[str] = Field(None, pattern="^(never|former|current|occasional)$")
    kb_status: Optional[str] = Field(None, pattern="^(shared|private)$")
    pack_name: Optional[str] = None
    agent_system_prompt: Optional[str] = Field(
        None,
        description="Полный пере-write системного промпта агента. Длинный (5-10к символов). Используй осторожно — лучше предложить пользователю diff перед применением.",
    )


@router.get("/profile_questionnaire")
async def profile_questionnaire(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Анкета пользователя — поля из users table, заполняемые в onboarding wizard.

    Возвращает: sex, height_cm, birth_date (+ возраст), timezone, smoking_status
    (never/former/current/occasional), kb_status (приватность knowledge_base —
    shared = доступно AI / private = только пользователю), garmin_connected,
    pack_name, agent_system_prompt (превью первых 500 симв).

    Используй когда юзер спрашивает «что я указывал в анкете», «какие у меня
    настройки приватности», «подключён ли Garmin». Также используй ПЕРЕД
    вызовом `update_profile_questionnaire` чтобы показать что изменится.
    """
    from datetime import date as date_cls

    age = None
    if user.birth_date:
        today = date_cls.today()
        age = (
            today.year
            - user.birth_date.year
            - ((today.month, today.day) < (user.birth_date.month, user.birth_date.day))
        )

    prompt = user.agent_system_prompt or ""
    return {
        "status": "ok",
        "profile": {
            "first_name": user.first_name,
            "sex": user.sex,
            "height_cm": user.height_cm,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "age": age,
            "timezone": user.timezone,
            "cohort": user.cohort,
            "smoking_status": getattr(user, "smoking_status", None),
            "kb_status": getattr(user, "kb_status", None),
            "pack_name": getattr(user, "pack_name", None),
            "garmin_connected": bool(user.garmin_email),
            "garmin_email": user.garmin_email,
        },
        "agent_system_prompt": {
            "length": len(prompt),
            "preview_500": prompt[:500] if prompt else None,
            "note": "Полный текст не возвращается из соображений размера. Используй update_profile_questionnaire чтобы заменить.",
        },
    }


@router.post("/update_profile_questionnaire")
async def update_profile_questionnaire(
    req: UpdateProfileRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Обновить анкетные поля. Только те что переданы — остальные не трогаются.

    SECURITY: agent_system_prompt — длинная строка, потенциально опасное поле
    (определяет поведение агента). Перед массовым переписыванием показать diff
    пользователю.
    """
    from sqlalchemy import text as sql_text
    from datetime import date as date_cls

    updates: dict[str, Any] = {}
    if req.sex is not None:
        updates["sex"] = req.sex
    if req.height_cm is not None:
        updates["height_cm"] = req.height_cm
    if req.birth_date is not None:
        try:
            date_cls.fromisoformat(req.birth_date)
            updates["birth_date"] = req.birth_date
        except ValueError:
            return {"status": "error", "error": f"invalid birth_date: {req.birth_date!r}"}
    if req.timezone is not None:
        updates["timezone"] = req.timezone
    if req.smoking_status is not None:
        updates["smoking_status"] = req.smoking_status
    if req.kb_status is not None:
        updates["kb_status"] = req.kb_status
    if req.pack_name is not None:
        updates["pack_name"] = req.pack_name
    if req.agent_system_prompt is not None:
        updates["agent_system_prompt"] = req.agent_system_prompt

    if not updates:
        return {"status": "noop", "reason": "no fields provided"}

    # Build dynamic UPDATE
    set_clause = ", ".join([f"{k} = :{k}" for k in updates])
    sql = f"UPDATE users SET {set_clause} WHERE telegram_id = :uid"
    params = {**updates, "uid": user.telegram_id}
    db.execute(sql_text(sql), params)
    db.commit()

    return {
        "status": "ok",
        "updated_fields": list(updates.keys()),
        "telegram_id": user.telegram_id,
    }


class SaveHealthProfileRequest(BaseModel):
    chronic_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    nothing_to_report: bool = False


@router.post("/save_health_profile")
async def save_health_profile(
    req: SaveHealthProfileRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Записать медпрофиль со слов пациента (#340).

    Онбординг-квиз про хроники и постоянные лекарства больше не спрашивает
    (шаг убран в f366c98), поэтому у самозарегистрированного юзера медпрофиль
    пуст, пока он не загрузит документ через /doc. Этот эндпоинт — второй
    канал: агент спрашивает в диалоге и сохраняет ответ.

    Пишет в те же ключи `users.onboarding_data`, откуда читают промпт-блок,
    отчёт для врача и /meal_context (реестр — core/health/onboarding_lists.py),
    через `merge_onboarding_lists` (дедуп case-insensitive).

    Флаг `health_profile_asked` ставится в любом случае — и когда что-то
    записали, и когда пользователю нечего сообщить: вопрос задан, повторять
    его не нужно.
    """
    from database.crud import get_user_by_telegram_id, merge_onboarding_lists

    added: dict[str, int] = {}
    if req.chronic_conditions or req.allergies:
        added = merge_onboarding_lists(
            db,
            user.telegram_id,
            {"allergies": req.allergies, "chronic_conditions": req.chronic_conditions},
        )

    row = get_user_by_telegram_id(db, user.telegram_id)
    if row is None:
        return {"status": "error", "error": "user not found"}
    data = dict(row.onboarding_data or {})
    data["health_profile_asked"] = True
    row.onboarding_data = data  # реассайн → SQLAlchemy видит изменение JSONB
    db.commit()

    return {
        "status": "ok",
        "added": added,
        "nothing_to_report": req.nothing_to_report,
        "health_profile_asked": True,
    }


@router.post("/update_user_settings")
async def update_user_settings_endpoint(
    req: UpdateUserSettingsRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Обновить настройки в user_settings table. Только переданные поля.

    Особенность: `supplements` — JSONB список, передача ПОЛНОСТЬЮ заменяет
    существующий режим. Чтобы добавить одну добавку — сначала get_user_settings,
    модифицировать список, затем update.
    """
    from sqlalchemy import text as sql_text
    from datetime import date as date_cls, time as time_cls
    import json as _json

    # Validate inputs
    if req.target_weight_date is not None:
        try:
            date_cls.fromisoformat(req.target_weight_date)
        except ValueError:
            return {"status": "error", "error": f"invalid target_weight_date: {req.target_weight_date!r}"}
    if req.supplement_reminder_time is not None:
        try:
            h, m = req.supplement_reminder_time.split(":")
            time_cls(int(h), int(m))
        except Exception:
            return {"status": "error", "error": f"invalid supplement_reminder_time: {req.supplement_reminder_time!r}"}

    updates: dict[str, Any] = {}
    for field in (
        "target_weight_kg",
        "target_weight_date",
        "calorie_goal_pct",
        "bmr_override",
        "bmr_source",
        "activity_level",
        "show_calorie_budget_bar",
        "supplement_reminders_enabled",
        "supplement_reminder_time",
    ):
        v = getattr(req, field)
        if v is not None:
            updates[field] = v

    # supplements нужен спецобработка как JSONB
    if req.supplements is not None:
        updates["supplements"] = _json.dumps(req.supplements, ensure_ascii=False)

    if not updates:
        return {"status": "noop", "reason": "no fields provided"}

    # UPSERT: если settings row ещё нет — создать
    cols_to_check = ", ".join([f"'{k}'" for k in updates])  # noqa: F841 (debug only)

    # Check if row exists
    exists = db.execute(
        sql_text("SELECT 1 FROM user_settings WHERE user_id = :uid"),
        {"uid": user.telegram_id},
    ).fetchone()

    params: dict[str, Any] = {**updates, "uid": user.telegram_id}
    if exists:
        set_clause = ", ".join([f"{k} = :{k}" for k in updates])
        # supplements — explicit jsonb cast
        if "supplements" in updates:
            set_clause = set_clause.replace("supplements = :supplements", "supplements = (:supplements)::jsonb")
        set_clause += ", updated_at = NOW()"
        db.execute(sql_text(f"UPDATE user_settings SET {set_clause} WHERE user_id = :uid"), params)
    else:
        cols = list(updates.keys()) + ["user_id"]
        vals = [f"(:{c})::jsonb" if c == "supplements" else f":{c}" for c in updates] + [":uid"]
        db.execute(
            sql_text(f"INSERT INTO user_settings ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )
    db.commit()

    return {
        "status": "ok",
        "updated_fields": list(updates.keys()),
        "telegram_id": user.telegram_id,
        "row_created": not bool(exists),
    }


@router.get("/user_settings")
async def user_settings(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Настройки пользователя: целевой вес, ежедневные добавки, BMR, цель калорий.

    Источник: `user_settings` table (per-user JSONB с регулярным режимом
    добавок) + поля из `users` (sex, height, birth_date, timezone, smoking_status).
    Используй для 'какие у меня цели', 'какие добавки я регулярно принимаю',
    'какой у меня дефицит калорий', 'когда у меня запланированы напоминания'.
    """
    from sqlalchemy import text as sql_text

    row = db.execute(
        sql_text(
            """
            SELECT show_calorie_budget_bar, bmr_override, target_weight_kg,
                   target_weight_date, supplement_reminders_enabled,
                   supplement_reminder_time, supplements, calorie_goal_pct,
                   bmr_source, activity_level, activity_avg_override
            FROM user_settings WHERE user_id = :uid
            """
        ),
        {"uid": user.telegram_id},
    ).fetchone()

    profile = {
        "first_name": user.first_name,
        "sex": user.sex,
        "height_cm": user.height_cm,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "timezone": user.timezone,
        "cohort": user.cohort,
        "smoking_status": getattr(user, "smoking_status", None),
        "garmin_connected": bool(user.garmin_email),
    }

    if not row:
        return {"status": "no_settings", "profile": profile, "reason": "user_settings row not created yet"}

    return {
        "status": "ok",
        "profile": profile,
        "goals": {
            "target_weight_kg": row.target_weight_kg,
            "target_weight_date": row.target_weight_date.isoformat() if row.target_weight_date else None,
            "calorie_goal_pct": row.calorie_goal_pct,
        },
        "bmr": {
            "source": row.bmr_source,
            "override": row.bmr_override,
            "activity_level": row.activity_level,
            "activity_avg_override": row.activity_avg_override,
        },
        "supplements_regimen": row.supplements or [],
        "reminders": {
            "supplement_enabled": row.supplement_reminders_enabled,
            "supplement_time": row.supplement_reminder_time.isoformat() if row.supplement_reminder_time else None,
        },
    }


@router.get("/user_profile")
async def user_profile(
    user=Depends(get_agent_user),
):
    """Return non-sensitive user profile info."""
    return {
        "status": "ok",
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "username": getattr(user, "username", None),
        "cohort": user.cohort,
        "container_id": user.container_id,
        "pack_name": user.pack_name,
        "garmin_email": user.garmin_email,  # intentionally included: agent needs to label data sources
        # NOTE: garmin_password is intentionally excluded
        "health_token": user.health_token,
        "timezone": getattr(user, "timezone", "Europe/Moscow"),
        "sex": getattr(user, "sex", None),
        "height_cm": getattr(user, "height_cm", None),
        "birth_date": user.birth_date.isoformat() if getattr(user, "birth_date", None) else None,
    }
