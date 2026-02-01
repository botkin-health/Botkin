
import os
import sys
import shutil
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.ocr_weight import parse_weight_screenshot
from core.weights import save_weight_measurement
from core.api_key_loader import get_google_vision_api_key
from core.chatgpt_vision import get_openai_api_key

def main():
    print("Starting Weight Reprocessing...")
    
    # Paths
    weights_today = Path("data/weights/2026-01-24.json")
    media_dir = Path("data/media/nutrition/2026-01-24")
    
    # 1. Backup and delete corrupted file
    if weights_today.exists():
        print(f"Removing corrupted file: {weights_today}")
        weights_today.unlink()
        
    # 2. Get images
    if not media_dir.exists():
        print("No media directory found!")
        return
        
    files = sorted(list(media_dir.glob("*.jpg")))
    print(f"Found {len(files)} images to process.")
    
    # 3. Keys
    api_key = get_google_vision_api_key() or os.getenv("GOOGLE_VISION_API_KEY")
    openai_key = get_openai_api_key()
    
    # 4. Process
    for idx, img_path in enumerate(files, 1):
        print(f"[{idx}/{len(files)}] Processing {img_path.name}...")
        try:
            # We don't have descriptions, pass empty
            data = parse_weight_screenshot([img_path], api_key, "")
            
            if data and data.get('weight'):
                print(f"  -> Found weight: {data.get('weight')} kg, Date: {data.get('date')}")
                data['source'] = 'reprocessed_ocr'
                save_path = save_weight_measurement(data)
                print(f"  -> Saved to: {save_path}")
            else:
                print("  -> No weight data found.")
                
        except Exception as e:
            print(f"Error processing {img_path.name}: {e}")

if __name__ == "__main__":
    main()
