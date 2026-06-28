"""Юнит-тесты log_food_interaction — наблюдаемость пищевого pipeline (#193)."""

from unittest.mock import patch

from core.food.interaction_log import get_food_interactions, log_food_interaction
from database.models import FoodInteraction


def test_logs_full_interaction(test_db):
    # Arrange / Act
    with patch("core.food.interaction_log.SessionLocal", return_value=test_db):
        log_food_interaction(
            user_id=12345,
            source="photo",
            raw_text="боул с киноа",
            media_path="data/media/photo_1.jpg",
            recognized={"items": [{"food": "Боул", "calories": 511}], "totals": {"calories": 511}},
            bot_reply="Записал: Боул — 511 ккал",
            nutrition_log_id=777,
            status="saved",
        )

    # Assert
    rows = test_db.query(FoodInteraction).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == 12345
    assert row.source == "photo"
    assert row.raw_text == "боул с киноа"
    assert row.media_path == "data/media/photo_1.jpg"
    assert row.recognized["totals"]["calories"] == 511
    assert row.bot_reply == "Записал: Боул — 511 ккал"
    assert row.nutrition_log_id == 777
    assert row.status == "saved"
    assert row.created_at is not None


def test_text_source_minimal_fields(test_db):
    with patch("core.food.interaction_log.SessionLocal", return_value=test_db):
        log_food_interaction(user_id=1, source="text", raw_text="съел банан 120г")

    row = test_db.query(FoodInteraction).one()
    assert row.source == "text"
    assert row.raw_text == "съел банан 120г"
    assert row.media_path is None
    assert row.recognized is None
    assert row.nutrition_log_id is None
    assert row.status == "saved"  # дефолт


def test_status_variants_accepted(test_db):
    with patch("core.food.interaction_log.SessionLocal", return_value=test_db):
        for st in ("saved", "cancelled", "edited"):
            log_food_interaction(user_id=2, source="text", raw_text="x", status=st)

    statuses = {r.status for r in test_db.query(FoodInteraction).all()}
    assert statuses == {"saved", "cancelled", "edited"}


def test_invalid_source_skipped(test_db):
    with patch("core.food.interaction_log.SessionLocal", return_value=test_db):
        log_food_interaction(user_id=3, source="sms", raw_text="x")

    assert test_db.query(FoodInteraction).count() == 0


def test_invalid_status_skipped(test_db):
    with patch("core.food.interaction_log.SessionLocal", return_value=test_db):
        log_food_interaction(user_id=4, source="text", raw_text="x", status="bogus")

    assert test_db.query(FoodInteraction).count() == 0


def test_never_raises_on_db_error():
    # SessionLocal бросает — хелпер обязан проглотить и не упасть.
    with patch("core.food.interaction_log.SessionLocal", side_effect=RuntimeError("db down")):
        result = log_food_interaction(user_id=5, source="text", raw_text="x")
    assert result is None


# ── read-side: get_food_interactions ─────────────────────────────────────────


def _add(db, user_id, raw_text):
    db.add(FoodInteraction(user_id=user_id, source="text", raw_text=raw_text, status="saved"))
    db.commit()


def test_get_food_interactions_filters_by_user_and_newest_first(test_db):
    _add(test_db, 100, "первое")
    _add(test_db, 100, "второе")
    _add(test_db, 999, "чужое")
    _add(test_db, 100, "третье")

    rows = get_food_interactions(test_db, 100)

    # только user 100, новые первыми (id desc при равном created_at)
    assert [r.raw_text for r in rows] == ["третье", "второе", "первое"]
    assert all(r.user_id == 100 for r in rows)


def test_get_food_interactions_respects_limit(test_db):
    for i in range(5):
        _add(test_db, 200, f"msg{i}")

    rows = get_food_interactions(test_db, 200, limit=2)
    assert len(rows) == 2


def test_get_food_interactions_empty_for_unknown_user(test_db):
    _add(test_db, 300, "x")
    assert get_food_interactions(test_db, 404) == []
