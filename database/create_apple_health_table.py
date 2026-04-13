"""
Script to create AppleHealthData table in the database
Run once to add the new table for Apple Health integration
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import engine
from database.models import AppleHealthData
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_apple_health_table():
    """Create apple_health_data table if it doesn't exist"""
    try:
        # Create only AppleHealthData table
        AppleHealthData.__table__.create(engine, checkfirst=True)
        logger.info("✅ AppleHealthData table created successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error creating table: {e}")
        return False


if __name__ == "__main__":
    logger.info("Creating AppleHealthData table...")
    success = create_apple_health_table()

    if success:
        print("\n✅ Database ready for Apple Health import!")
        print("Use /import_health in the bot to start importing data")
    else:
        print("\n❌ Failed to create table. Check logs above.")
