"""
Apple Health Export XML Parser
Supports multi-user import with data isolation
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

# Apple Health data type mappings
SUPPORTED_TYPES = {
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "blood_pressure_sys",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "blood_pressure_dia",
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKCategoryTypeIdentifierSleepAnalysis": "sleep",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
}


def parse_export_xml(xml_path: str, user_id: int) -> Dict[str, List[Dict]]:
    """
    Parse Apple Health export.xml

    Args:
        xml_path: Path to export.xml
        user_id: Telegram user ID

    Returns:
        Dict with categorized health data
    """
    logger.info(f"Parsing Apple Health export for user {user_id}: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    results = {
        "weight": [],
        "blood_pressure": [],
        "heart_rate": [],
        "sleep": [],
        "hrv": [],
        "body_fat": [],
        "resting_heart_rate": [],
    }

    # Temporary storage for blood pressure pairing
    bp_systolic = {}
    bp_diastolic = {}

    # Parse Record elements
    for record in root.findall(".//Record"):
        record_type = record.get("type")

        if record_type not in SUPPORTED_TYPES:
            continue

        data_type = SUPPORTED_TYPES[record_type]

        # Extract common fields
        value_str = record.get("value", "0")
        try:
            value = float(value_str)
        except ValueError:
            logger.warning(f"Invalid value '{value_str}' for {record_type}")
            continue

        unit = record.get("unit", "")
        start_date_str = record.get("startDate", "")

        # Parse ISO datetime
        try:
            # Handle format like "2026-01-15 12:30:45 +0300"
            if "+" in start_date_str or "-" in start_date_str[-6:]:
                start_date = datetime.fromisoformat(start_date_str.replace(" ", "T").replace(" ", ""))
            else:
                start_date = datetime.fromisoformat(start_date_str)
        except ValueError:
            logger.warning(f"Invalid date format: {start_date_str}")
            continue

        source = record.get("sourceName", "Unknown")
        device = record.get("device", "")

        # Build base entry
        entry = {
            "user_id": user_id,
            "recorded_at": start_date,
            "source_name": source,
            "device": device if device else None,
        }

        # Type-specific processing
        if data_type == "weight":
            entry["data_type"] = "weight"
            entry["value"] = {"value": value, "unit": unit}
            results["weight"].append(entry)

        elif data_type == "blood_pressure_sys":
            # Store for pairing with diastolic
            key = (start_date, source)
            bp_systolic[key] = value

        elif data_type == "blood_pressure_dia":
            # Try to pair with systolic
            key = (start_date, source)
            bp_diastolic[key] = value

        elif data_type == "heart_rate":
            entry["data_type"] = "heart_rate"
            entry["value"] = {"bpm": int(value)}
            results["heart_rate"].append(entry)

        elif data_type == "resting_heart_rate":
            entry["data_type"] = "resting_heart_rate"
            entry["value"] = {"bpm": int(value)}
            results["resting_heart_rate"].append(entry)

        elif data_type == "hrv":
            entry["data_type"] = "hrv"
            entry["value"] = {"sdnn_ms": value}
            results["hrv"].append(entry)

        elif data_type == "body_fat":
            entry["data_type"] = "body_fat"
            entry["value"] = {"percentage": value, "unit": unit}
            results["body_fat"].append(entry)

    # Pair blood pressure measurements
    for key, systolic in bp_systolic.items():
        if key in bp_diastolic:
            date, source = key
            entry = {
                "user_id": user_id,
                "data_type": "blood_pressure",
                "recorded_at": date,
                "value": {"systolic": int(systolic), "diastolic": int(bp_diastolic[key]), "unit": "mmHg"},
                "source_name": source,
                "device": None,
            }
            results["blood_pressure"].append(entry)

    # Log summary
    total = sum(len(v) for v in results.values())
    logger.info(f"Parsed {total} health records: " + ", ".join(f"{k}={len(v)}" for k, v in results.items() if v))

    return results


def deduplicate_data(data_list: List[Dict]) -> List[Dict]:
    """
    Remove duplicate entries by (user_id, timestamp)
    Keep the most recent imported record
    """
    seen = set()
    unique = []

    # Sort by timestamp to keep consistent order
    sorted_data = sorted(data_list, key=lambda x: x["recorded_at"])

    for item in sorted_data:
        key = (item["user_id"], item["recorded_at"].isoformat())
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique
