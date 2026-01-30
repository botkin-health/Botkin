
import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.ocr_weight import parse_weight_screenshot
from core.weights import save_weight_measurement
from core.api_key_loader import get_google_vision_api_key
from core.chatgpt_vision import get_openai_api_key

def main():
    print("Processing new 2025 updates...")
    
    media_dir = Path("data/media/nutrition/2025_updates")
    if not media_dir.exists():
        print("No media directory found!")
        return
        
    files = sorted(list(media_dir.glob("*")))
    print(f"Found {len(files)} new images.")
    
    api_key = get_google_vision_api_key() or os.getenv("GOOGLE_VISION_API_KEY")
    
    for img_path in files:
        if img_path.name.startswith('.'): continue
        print(f"Processing {img_path.name}...")
        try:
            data = parse_weight_screenshot([img_path], api_key, "")
            
            if data and data.get('weight'):
                print(f"  -> Found: {data.get('weight')}kg, Fat: {data.get('body_fat')}%, Muscle: {data.get('muscle')}, Visceral: {data.get('visceral_fat')}, Date: {data.get('date')}")
                
                # Force save to correct date file
                save_path = save_weight_measurement(data)
                print(f"  -> Saved to: {save_path}")
            else:
                print("  -> No extracted data.")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
