#!/usr/bin/env python3
"""
Tests for multi-user authorization and data isolation.
"""

import pytest
from datetime import date, time
from database.models import NutritionLog
from database.crud import ensure_user_exists, get_nutrition_logs_by_period
from config.users import ADMIN_USER_ID, is_admin


class TestMultiUserAuth:
    """Tests for multi-user authorization"""

    def test_admin_user_is_admin(self):
        """Test that main admin user has admin privileges"""
        assert is_admin(ADMIN_USER_ID) is True

    def test_random_user_is_not_admin(self):
        """Test that random users don't have admin privileges"""
        assert is_admin(999999999) is False

    def test_ensure_user_creates_new_user(self, test_db):
        """Test that ensure_user_exists creates new users — open registration"""
        test_user_id = 123456789

        user = ensure_user_exists(test_db, telegram_id=test_user_id, username="test_user", first_name="Test")

        assert user is not None
        assert user.telegram_id == test_user_id
        assert user.username == "test_user"
        assert user.first_name == "Test"
        assert user.is_active is True

    def test_ensure_user_updates_existing(self, test_db):
        """Test that ensure_user_exists updates existing users"""
        test_user_id = 987654321

        # Create user first time
        user1 = ensure_user_exists(test_db, telegram_id=test_user_id, username="user1")

        # Call again - should update, not duplicate
        user2 = ensure_user_exists(test_db, telegram_id=test_user_id, username="user1")

        assert user1.telegram_id == user2.telegram_id
        assert user2.last_active is not None

    def test_new_user_gets_default_settings(self, test_db):
        """Test that new users get UserSettings with sane defaults"""
        from database.crud import get_user_settings

        test_user_id = 777000111
        ensure_user_exists(test_db, telegram_id=test_user_id, username="newbie")

        settings = get_user_settings(test_db, test_user_id)
        assert settings is not None
        assert settings.calorie_goal_pct == -15
        assert settings.show_calorie_budget_bar is True


class TestDataIsolation:
    """Tests for user data isolation"""

    def test_users_cannot_see_others_nutrition_logs(self, test_db):
        """Test that users can't access each other's nutrition data"""
        user1_id = 895655
        user2_id = 999999

        # Ensure both users exist
        ensure_user_exists(test_db, user1_id, "user1")
        ensure_user_exists(test_db, user2_id, "user2")

        # User 1 logs food
        log1 = NutritionLog(
            user_id=user1_id,
            date=date.today(),
            meal_time=time(12, 0),
            meal_name="обед",
            items=[{"name": "курица", "weight": 100}],
            totals={"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0},
        )
        test_db.add(log1)
        test_db.commit()

        # User 2 shouldn't see user 1's data
        user2_logs = get_nutrition_logs_by_period(test_db, user2_id, date.today(), date.today())

        assert len(user2_logs) == 0

        # User 1 should see their own data
        user1_logs = get_nutrition_logs_by_period(test_db, user1_id, date.today(), date.today())

        assert len(user1_logs) == 1
        assert user1_logs[0].user_id == user1_id

    def test_different_users_can_have_same_date_logs(self, test_db):
        """Test that multiple users can log data on the same date"""
        user1_id = 100001
        user2_id = 100002

        ensure_user_exists(test_db, user1_id, "user1")
        ensure_user_exists(test_db, user2_id, "user2")

        today = date.today()

        # Both users log food on same date
        for uid in [user1_id, user2_id]:
            log = NutritionLog(
                user_id=uid,
                date=today,
                meal_time=time(12, 0),
                meal_name="обед",
                items=[{"name": "еда", "weight": 100}],
                totals={"calories": 200, "protein": 10, "fats": 5, "carbs": 20},
            )
            test_db.add(log)

        test_db.commit()

        # Each user should only see their own log
        user1_logs = get_nutrition_logs_by_period(test_db, user1_id, today, today)
        user2_logs = get_nutrition_logs_by_period(test_db, user2_id, today, today)

        assert len(user1_logs) == 1
        assert len(user2_logs) == 1
        assert user1_logs[0].user_id == user1_id
        assert user2_logs[0].user_id == user2_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
