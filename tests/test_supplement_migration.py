"""Unit tests for the multi-user supplement defaults / migration logic (PR #72).

Context — these guard the multi-user safety fix:
- DEFAULT_SUPPLEMENTS no longer carries the owner's personal protocol, so new
  users must NOT inherit anyone else's supplements.
- migrate_legacy_supplements() fixes only STRUCTURAL issues (deprecated slot,
  over-long doses) while preserving each user's own list — it must never wipe data.
- dose_from_user_schedule() resolves a dose from the user's OWN configured
  schedule only — never a cross-user default.

Pure functions, no DB needed.
"""

from core.health.supplements import (
    DEFAULT_SUPPLEMENTS,
    dose_from_user_schedule,
    migrate_legacy_supplements,
    needs_legacy_migration,
)


def test_default_supplements_is_empty():
    # New users must not inherit anyone's personal protocol.
    assert DEFAULT_SUPPLEMENTS == []


# --- needs_legacy_migration -------------------------------------------------


def test_empty_list_does_not_need_migration():
    # Empty == user explicitly cleared their schedule; never "migrate" it.
    assert needs_legacy_migration([]) is False


def test_deprecated_post_workout_slot_needs_migration():
    assert needs_legacy_migration([{"name": "Whey", "slot": "post_workout", "dose": "2 ложки"}]) is True


def test_over_long_dose_needs_migration():
    assert needs_legacy_migration([{"name": "X", "slot": "evening", "dose": "a" * 13}]) is True


def test_well_formed_schedule_does_not_need_migration():
    assert needs_legacy_migration([{"name": "Магний", "slot": "evening", "dose": "2 табл"}]) is False


# --- migrate_legacy_supplements --------------------------------------------


def test_migration_remaps_post_workout_to_evening():
    result = migrate_legacy_supplements([{"name": "Whey", "slot": "post_workout", "dose": "2 ложки"}])
    assert result == [{"name": "Whey", "slot": "evening", "dose": "2 ложки"}]


def test_migration_truncates_over_long_dose():
    result = migrate_legacy_supplements([{"name": "X", "slot": "evening", "dose": "1234567890123456"}])
    assert len(result[0]["dose"]) <= 12


def test_migration_preserves_user_own_list_not_owner_defaults():
    # The user's own supplements must survive migration verbatim (names preserved).
    original = [
        {"name": "Витамин C", "slot": "morning_with", "dose": "500 мг"},
        {"name": "Цинк", "slot": "evening", "dose": "15 мг"},
    ]
    result = migrate_legacy_supplements(original)
    assert [r["name"] for r in result] == ["Витамин C", "Цинк"]


def test_migration_drops_malformed_entries():
    result = migrate_legacy_supplements(
        [
            {"name": "Магний", "slot": "evening", "dose": "2 табл"},
            {"slot": "evening", "dose": "1 табл"},  # no name → dropped
            "garbage",  # not a dict → dropped
        ]
    )
    assert result == [{"name": "Магний", "slot": "evening", "dose": "2 табл"}]


def test_migration_defaults_missing_slot():
    result = migrate_legacy_supplements([{"name": "Магний", "dose": "2 табл"}])
    assert result[0]["slot"] == "morning_with"


# --- dose_from_user_schedule -----------------------------------------------


def test_dose_resolved_from_users_own_schedule():
    planned = [{"name": "Витамин D3", "slot": "morning_with", "dose": "5000 IU"}]
    assert dose_from_user_schedule(planned, "Витамин D3") == "5000 IU"


def test_dose_matches_via_name_synonyms():
    # "D3" is a synonym of "Витамин D3" — must still resolve the dose.
    planned = [{"name": "Витамин D3", "slot": "morning_with", "dose": "5000 IU"}]
    assert dose_from_user_schedule(planned, "D3") == "5000 IU"


def test_dose_is_none_when_not_in_schedule():
    planned = [{"name": "Магний", "slot": "evening", "dose": "2 табл"}]
    assert dose_from_user_schedule(planned, "Креатин") is None


def test_dose_is_none_for_empty_schedule():
    # No cross-user default: an unconfigured user gets no dose stamped.
    assert dose_from_user_schedule([], "Магний") is None
    assert dose_from_user_schedule(None, "Магний") is None
