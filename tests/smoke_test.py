#!/usr/bin/env python3
"""Quick smoke test for critical bot functions"""

import sys
sys.path.insert(0, '/Users/alexlyskovsky/HealthVault')

from database import SessionLocal, get_nutrition_logs_by_period, get_last_activity_date
from datetime import date, timedelta
from core.weekly_nutrition import analyze_weekly_nutrition

def test_database_connection():
    """Test Postgres connection"""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        result = db.execute(text("SELECT 1"))
        assert result.fetchone()[0] == 1
        print("✅ Database connection OK")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    finally:
        db.close()

def test_garmin_last_date():
    """Test get_last_activity_date function"""
    db = SessionLocal()
    try:
        last_date = get_last_activity_date(db, 895655)
        print(f"✅ Last Garmin date: {last_date}")
        return last_date is not None
    except Exception as e:
        print(f"❌ get_last_activity_date failed: {e}")
        return False
    finally:
        db.close()

def test_weekly_analysis():
    """Test weekly nutrition analysis"""
    try:
        result = analyze_weekly_nutrition(user_id=895655)
        days = result.get('days_analyzed', 0)
        print(f"✅ Weekly analysis OK: {days} days")
        
        # Check saira detection
        fatty_fish = result.get('categories', {}).get('fatty_fish_portions', 0)
        print(f"   Fatty fish portions: {fatty_fish:.1f}")
        
        # Check if saira was detected (should be > 0 if user ate it)
        if fatty_fish > 0:
            print("   ✅ Saira detection working!")
        
        return True
    except Exception as e:
        print(f"❌ Weekly analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_nutrition_logs():
    """Test nutrition log retrieval"""
    db = SessionLocal()
    try:
        today = date.today()
        week_ago = today - timedelta(days=7)
        logs = get_nutrition_logs_by_period(db, 895655, week_ago, today)
        print(f"✅ Nutrition logs OK: {len(logs)} entries found")
        return True
    except Exception as e:
        print(f"❌ Nutrition logs failed: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("\n🧪 Running Bot Smoke Tests...\n")
    
    results = [
        test_database_connection(),
        test_garmin_last_date(),
        test_weekly_analysis(),
        test_nutrition_logs()
    ]
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!\n")
        exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed!\n")
        exit(1)
