
import json
import os
from pathlib import Path

WEIGHTS_DIR = Path("/Users/alexlyskovsky/HealthVault/data/weights")

def fix_visceral_fat():
    files = list(WEIGHTS_DIR.glob("*.json"))
    fixed_count = 0
    
    for file_path in files:
        if file_path.name in ["body_measurements.json", "apple_health_weights.json", "zepp_reminders.json"]:
            continue
            
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            modified = False
            
            # Data is usually a list of dicts or a single dict? 
            # From view_file, it's a list: [{"Name": ...}]
            
            if not isinstance(data, list):
                # Handle single dict if exists (legacy?)
                data_list = [data]
                is_list = False
            else:
                data_list = data
                is_list = True

            for entry in data_list:
                # Logic: If body_fat is present and < 20, AND visceral_fat is NOT present, move it.
                # User's BMI is around 28-29 (Overweight), so body fat < 20% is highly unlikely (athletic range).
                # Visceral fat is usually 13-16.
                
                body_fat = entry.get("body_fat")
                visceral_fat = entry.get("visceral_fat")
                
                if body_fat is not None and isinstance(body_fat, (int, float)):
                    if 1.0 < float(body_fat) < 22.0: # Range check
                        if visceral_fat is None:
                            print(f"🔧 Fixing {file_path.name}: Moving Body Fat {body_fat} to Visceral Fat")
                            entry["visceral_fat"] = body_fat
                            # Remove body_fat or keep it? 
                            # If we move it, we should probably remove the wrong key. 
                            # But maybe we should recalculate body_fat approx? No, better leave it empty than wrong.
                            del entry["body_fat"] 
                            modified = True
                        else:
                            print(f"⚠️  Skipping {file_path.name}: Has both Body Fat {body_fat} and Visceral {visceral_fat}. Check manually.")
            
            if modified:
                with open(file_path, 'w', encoding='utf-8') as f:
                    # Write updated data back
                    json.dump(data if is_list else data_list[0], f, ensure_ascii=False, indent=2)
                fixed_count += 1
                
        except Exception as e:
            print(f"❌ Error processing {file_path.name}: {e}")

    print(f"\n✅ Finished. Parsed {len(files)} files. Fixed {fixed_count} files.")

if __name__ == "__main__":
    fix_visceral_fat()
