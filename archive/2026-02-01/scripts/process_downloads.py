
import os
import shutil
import hashlib
import re
import sys
from pathlib import Path
from datetime import datetime
import pypdf

# Config
DOWNLOADS_DIR = Path.home() / "Downloads"
HEALTH_VAULT_ROOT = Path(__file__).parent.parent
DATA_DIR = HEALTH_VAULT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"

# Output for report
NEW_ANALYSES_CONTENT = []

def get_file_hash(path):
    """Calculate SHA256 of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        print(f"Error hashing {path}: {e}")
        return None

def extract_pdf_text(path):
    """Extract text from PDF using pypdf."""
    text = ""
    try:
        reader = pypdf.PdfReader(path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        print(f"Error reading PDF {path}: {e}")
    return text

def parse_invitro_date(text):
    """Extract date from Invitro text (DD.MM.YYYY)."""
    # Look for "Дата взятия биоматериала: DD.MM.YYYY" or similar
    match = re.search(r"Дата взятия.*?:?\s*(\d{2}\.\d{2}\.\d{4})", text)
    if match:
        return match.group(1)
    
    # Fallback: look for any date pattern near "Дата"
    dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", text)
    if dates:
        return dates[0] # Return first found date
    return None

def parse_invitro_id(text):
    """Extract Order ID (ИНЗ) from text."""
    match = re.search(r"ИНЗ:\s*(\d+)", text)
    if match:
        return match.group(1)
    return None

def determine_type(text):
    """Determine analysis type from text content."""
    text_lower = text.lower()
    if "клинический анализ крови" in text_lower or "общий анализ крови" in text_lower:
        return "blood", "general"
    if "биохимия" in text_lower or "биохимически" in text_lower:
        return "blood", "biochemistry"
    if "общий анализ мочи" in text_lower:
        return "urine", "general"
    if "25-oh" in text_lower or "витамин d" in text_lower:
        return "blood", "vitamin-d"
    if "ферритин" in text_lower:
        return "blood", "ferritin"
    if "ттг" in text_lower or "тиреотропный" in text_lower:
        return "hormones", "ttg"
    if "тестостерон" in text_lower:
        return "hormones", "testosterone"
    
    # Default fallback
    return "blood", "other"

def main():
    print("🚀 Starting analysis processing...")
    
    # 1. Index existing files
    print("🔍 Indexing existing files in HealthVault...")
    existing_hashes = {}
    existing_files_count = 0
    
    for path in DATA_DIR.rglob("*.pdf"):
        file_hash = get_file_hash(path)
        if file_hash:
            existing_hashes[file_hash] = path
            existing_files_count += 1
            
    print(f"✅ Indexed {existing_files_count} existing files.")

    # 2. Scan Downloads
    print(f"📂 Scanning {DOWNLOADS_DIR}...")
    # Filter for likely analysis files (start with digit or contain specific keywords)
    candidates = []
    for file in DOWNLOADS_DIR.glob("*.pdf"):
        if re.match(r"^\d+.*\.pdf", file.name) or "invitro" in file.name.lower() or "cmd" in file.name.lower():
            candidates.append(file)
            
    print(f"Found {len(candidates)} potential medical files.")
    
    processed_count = 0
    deleted_count = 0
    moved_count = 0
    
    for file_path in candidates:
        print(f"Processing: {file_path.name}")
        
        # Check specific exclude match (from user screenshot, some looked like unrelated docs but starting with digits)
        # Assuming typical Invitro is purely digits + name. 
        # But let's process content to be sure.
        
        # Hash check
        current_hash = get_file_hash(file_path)
        if current_hash in existing_hashes:
            print(f"  🗑️ Duplicate contents found in {existing_hashes[current_hash]}. Deleting...")
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                print(f"  ❌ Failed to delete: {e}")
            continue
            
        # Determine content
        text = extract_pdf_text(file_path)
        if not text or len(text) < 100:
            print("  ⚠️ Only image or empty PDF. Skipping for now (needs OCR).")
            continue
            
        # Check if it's really medical (look for Lab keywords)
        is_medical = "invitro" in text.lower() or "инвитро" in text.lower() or "cmd" in text.lower() or "гемотест" in text.lower()
        if not is_medical:
            print("  ⚠️ Not recognized as a known lab report. Skipping.")
            continue
            
        # Extract metadata
        date_str = parse_invitro_date(text)
        order_id = parse_invitro_id(text)
        
        if not date_str:
            print("  ⚠️ Could not parse date. Skipping.")
            continue
            
        # Format date YYYY-MM-DD
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            formatted_date = dt.strftime("%Y-%m-%d")
        except:
            print(f"  ⚠️ Invalid date format: {date_str}")
            continue
            
        category, sub_type = determine_type(text)
        source = "invitro" if "инвитро" in text.lower() else "cmd" if "cmd" in text.lower() else "unknown"
        
        # Construct new name
        new_name = f"{category}_{source}_{formatted_date}_{sub_type}.pdf"
        target_dir = DATA_DIR / f"{category}-tests"
        if not target_dir.exists():
            target_dir = DATA_DIR / "medical-records" # Fallback
            
        target_path = target_dir / new_name
        
        # Check for collision (same name but different hash - maybe duplicate text?)
        if target_path.exists():
            # If target exists but hash is different, append suffix
            print(f"  ⚠️ Target file exists: {target_path}")
            # Identify if it's the exact same analysis (same Order ID)
            existing_text = extract_pdf_text(target_path)
            if order_id and order_id in existing_text:
                 print("  🗑️ Semantic duplicate (same Order ID detected). Deleting...")
                 os.remove(file_path)
                 deleted_count += 1
                 continue
            else: 
                # Different analysis same day? rename
                new_name = f"{category}_{source}_{formatted_date}_{sub_type}_new.pdf"
                target_path = target_dir / new_name
        
        # Move
        print(f"  ✨ Moving to: {target_path}")
        try:
            if not target_dir.exists():
                target_dir.mkdir(parents=True)
            shutil.move(file_path, target_path)
            moved_count += 1
            NEW_ANALYSES_CONTENT.append(f"Date: {formatted_date}\nType: {sub_type}\nSource: {source}\nContent Snippet:\n{text[:2000]}...") # Keep first 2000 chars for report
        except Exception as e:
            print(f"  ❌ Failed to move: {e}")

    print("-" * 30)
    print(f"🏁 Finished.")
    print(f"  Deleted (Duplicates): {deleted_count}")
    print(f"  Moved (New): {moved_count}")
    print(f"  New content gathered for report: {len(NEW_ANALYSES_CONTENT)} files.")
    
    # Save collected text for the Agent to read
    if NEW_ANALYSES_CONTENT:
        with open(HEALTH_VAULT_ROOT / "new_analysis_summary.txt", "w") as f:
            f.write("\n---\n".join(NEW_ANALYSES_CONTENT))

if __name__ == "__main__":
    main()
