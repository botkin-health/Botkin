#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.chatgpt_vision import get_openai_api_key
import requests

def test_key():
    print("--- Verifying OpenAI API Key ---")
    key = get_openai_api_key()
    
    if not key:
        print("❌ Key NOT found!")
        return
        
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "INVALID_LEN"
    print(f"🔑 Loaded Key: {masked}")
    
    print("\nAttempting API call (List Models)...")
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ API Call Successful! Key is VALID.")
        elif response.status_code == 401:
            print("❌ 401 Unauthorized - Key is INVALID.")
        elif response.status_code == 403:
            print("❌ 403 Forbidden - Key lacks permissions or account inactive.")
            print(f"Response: {response.text}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_key()
