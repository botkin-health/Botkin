import sys
import os
from datetime import datetime, timedelta

# Add project root and telegram-bot to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'telegram-bot'))

from handlers.text import extract_date_from_text

def test_extract_date():
    today = datetime.now()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    
    test_cases = [
        ("Вчера ужин: яйцо", yesterday, "ужин: яйцо"),
        ("вчера: каша", yesterday, "каша"),
        ("Вчера, обед суп", yesterday, "обед суп"),
        ("yesterday breakfast", yesterday, "breakfast"),
        ("Сегодня ужин", None, "Сегодня ужин"),
        ("Просто текст", None, "Просто текст"),
        ("Вчера", yesterday, ""),
    ]
    
    print(f"Testing for Yesterday date: {yesterday}\n")
    
    passed = 0
    for text, expected_date, expected_clean in test_cases:
        date, clean = extract_date_from_text(text)
        is_date_ok = date == expected_date
        is_clean_ok = clean == expected_clean
        
        status = "✅" if is_date_ok and is_clean_ok else "❌"
        print(f"{status} Input: '{text}'")
        if not is_date_ok:
            print(f"   Expected Date: {expected_date}, Got: {date}")
        if not is_clean_ok:
            print(f"   Expected Text: '{expected_clean}', Got: '{clean}'")
            
        if is_date_ok and is_clean_ok:
            passed += 1
            
    print(f"\nPassed: {passed}/{len(test_cases)}")

if __name__ == "__main__":
    test_extract_date()
