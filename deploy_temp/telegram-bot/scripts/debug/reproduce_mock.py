
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to python path
project_root = Path("/Users/alexlyskovsky/HealthVault/telegram-bot")
sys.path.append(str(project_root))

# Pre-import to ensure we can patch
import services.chatgpt_vision
from services.description_parser import parse_meal_description

class TestDuplication(unittest.TestCase):
    @patch('services.chatgpt_vision.parse_text_description_with_chatgpt')
    @patch('services.chatgpt_vision.get_openai_api_key')
    def test_chatgpt_duplicates(self, mock_get_key, mock_parse_chatgpt):
        # Mock API Key existence (so the check passes)
        mock_get_key.return_value = "fake_key"
        
        # Mock ChatGPT returning duplicates
        mock_parse_chatgpt.return_value = [
            {'name': 'жареная картошка', 'weight': 150.0, 'source': 'chatgpt', 'basis': 'cooked'},
            {'name': 'жареная картошка', 'weight': 150.0, 'source': 'chatgpt', 'basis': 'cooked'}
        ]
        
        description = "150 грамм жаренной картошки"
        print(f"\nTesting with Mocked ChatGPT response (duplicates)...")
        
        # We need to make sure parse_meal_description uses the mocked functions
        # converting local import to global matching might be tricky if it re-imports
        # But sys.modules cache should handle it.
        
        products = parse_meal_description(description)
        
        print(f"Found {len(products)} products:")
        for p in products:
            print(f"  - {p['name']}: {p['weight']}g")
            
        # Assert that we have only 1 product (fix works)
        self.assertEqual(len(products), 1, "Should have 1 product (deduplication works)")
        print("VERIFIED: Fix works (duplicates are removed).")

if __name__ == "__main__":
    unittest.main()
