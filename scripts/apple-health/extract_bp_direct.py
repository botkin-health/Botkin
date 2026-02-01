
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
import csv

# Configuration
XML_FILE = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/export/export_20260201.xml")
OUTPUT_FILE = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/parsed/blood_pressure_manual.csv")

def parse_bp_from_xml():
    print(f"📖 Streaming parse of {XML_FILE}...")
    
    systolic_records = {} # key: (date), value: value
    diastolic_records = {} # key: (date), value: value
    
    # Using iterparse for memory efficiency
    context = ET.iterparse(XML_FILE, events=("end",))
    
    count = 0
    for event, elem in context:
        if elem.tag == "Record":
            r_type = elem.get("type")
            start_date = elem.get("startDate")
            value = elem.get("value")
            source = elem.get("sourceName")
            
            if r_type == "HKQuantityTypeIdentifierBloodPressureSystolic":
                systolic_records[start_date] = {"val": value, "src": source}
            elif r_type == "HKQuantityTypeIdentifierBloodPressureDiastolic":
                diastolic_records[start_date] = {"val": value, "src": source}
            
            # Clear element to save memory
            elem.clear()
            count += 1
            if count % 100000 == 0:
                print(f"Processed {count} records...")

    print(f"Found {len(systolic_records)} systolic and {len(diastolic_records)} diastolic records.")

    # Match them by date
    results = []
    
    # Systolic keys should match diastolic keys usually exactly in Apple Health for correlated samples
    # Or we proceed through all keys
    all_dates = set(systolic_records.keys()) | set(diastolic_records.keys())
    
    for date in all_dates:
        sys = systolic_records.get(date)
        dia = diastolic_records.get(date)
        
        if sys and dia:
             results.append({
                 "date": date,
                 "systolic": sys['val'],
                 "diastolic": dia['val'],
                 "source": sys['src']
             })
    
    # Sort
    results.sort(key=lambda x: x['date'], reverse=True)
    
    print(f"\n✅ Matched {len(results)} complete BP readings.")

    # Save to CSV
    with open(OUTPUT_FILE, "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Systolic", "Diastolic", "Source"])
        for r in results:
            writer.writerow([r['date'], r['systolic'], r['diastolic'], r['source']])
            
    print(f"💾 Saved to {OUTPUT_FILE}")
    
    # Display top 10
    print("\n📊 Latest 10 Readings:")
    print("-" * 65)
    print(f"{'Date':<25} | {'BP':<10} | {'Source'}")
    print("-" * 65)
    for r in results[:10]:
        # Format date for readability: 2026-01-30 08:12:00 +0300
        d_str = r['date'].replace(" +0300", "")
        bp_str = f"{int(float(r['systolic']))}/{int(float(r['diastolic']))}"
        print(f"{d_str:<25} | {bp_str:<10} | {r['source']}")

if __name__ == "__main__":
    parse_bp_from_xml()
