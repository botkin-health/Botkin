
from services.weekly_nutrition import generate_weekly_recommendations
from datetime import datetime

def test_status_formatting():
    # Mock data to trigger the recommendations
    totals = {'fiber': 10} # Low fiber (<25)
    categories = {
        'fatty_fish_portions': 1.0, # < 2
        'red_meat_portions': 1.0,
        'processed_meat_portions': 0.0,
        'high_carb_dinners': 0,
        'alcohol_days_count': 3 # > 2
    }
    dates_analyzed = ['2023-01-01'] * 7
    
    recs = generate_weekly_recommendations(totals, categories, dates_analyzed)
    
    print("Generated Recommendations:")
    error_found = False
    for r in recs:
        print(f"- {r}")
        if '<' in r and '&lt;' not in r:
             print("  FAIL: Found unescaped '<' symbol. This will break HTML parsing.")
             error_found = True
        elif '>' in r and '&gt;' not in r:
             # > is technically allowed in some HTML contexts but safer to escape
             print("  WARN: Found unescaped '>' symbol.")
             
    if error_found:
        print("\nCONFIRMED: Bug exists (unescaped HTML characters).")
    else:
        print("\nPASS: No unescaped characters found.")

if __name__ == "__main__":
    test_status_formatting()
