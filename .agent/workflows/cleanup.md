---
description: Cleanup temporary files and push changes to GitHub
---

1. Delete temporary medical analysis reports and one-off scripts:
   ```bash
   rm -f new_analysis_summary.txt
   rm -f data/blood-tests/blood_cmd_2025-08-10_general_extracted.txt
   rm -f scripts/separate_valeria.py
   rm -f scripts/filter_summary.py
   rm -f scripts/fix_invitro_names.py
   rm -f scripts/extract_emias_data.py
   ```

2. Add changes to git:
   ```bash
   git add .
   ```

3. Commit changes:
   ```bash
   git commit -m "chore: cleanup temporary files and update Knowledge Base with recent analyzes"
   ```

4. Push to remote:
   ```bash
   git push
   ```
