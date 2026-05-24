#!/usr/bin/env bash
# Migrate kb_*.json from /opt/healthvault/ → /opt/healthvault/data/kb/
#
# One-shot migration after the layout refactor (2026-05-24). Safe to re-run:
# - mkdir is idempotent
# - mv skips already-moved files (no-op if source missing)
# - Old per-file bind-mounts in docker-compose.prod.yml must already be removed
#   before this runs (otherwise mv hits "Device or resource busy").
#
# Run on the Hetzner box:
#   ssh root@116.203.213.137 bash < scripts/migrate_kb_layout.sh

# NB: no `set -e` — `ls *.json` returns rc=1 when no matches and would abort
# the whole migration on a freshly-migrated environment. We handle errors
# explicitly per-step instead.
set -uo pipefail

DEPLOY_ROOT="/opt/healthvault"
TARGET_DIR="$DEPLOY_ROOT/data/kb"

echo "== Pre-flight =="
shopt -s nullglob
src_files=( "$DEPLOY_ROOT"/kb_*.json )
dst_files=( "$TARGET_DIR"/kb_*.json )
echo "files in root: ${#src_files[@]}"
echo "files in data/kb already: ${#dst_files[@]}"

echo ""
echo "== Ensure target dir =="
mkdir -p "$TARGET_DIR"

echo ""
echo "== Move files =="
shopt -s nullglob
moved=0
for f in "$DEPLOY_ROOT"/kb_*.json; do
    name=$(basename "$f")
    target="$TARGET_DIR/$name"
    if [ -f "$target" ]; then
        # If both exist, the source is likely the bind-mount endpoint from old
        # compose. Compare content; if identical, just remove source.
        if cmp -s "$f" "$target"; then
            rm -f "$f"
            echo "  ✓ $name — identical at target, removed source"
        else
            echo "  ⚠ $name — DIFFERS at target. Skipping (manual review needed)"
        fi
    else
        mv "$f" "$target"
        echo "  ✓ $name → data/kb/"
        moved=$((moved+1))
    fi
done
shopt -u nullglob

echo ""
echo "== After =="
echo "files in root: $(ls "$DEPLOY_ROOT"/kb_*.json 2>/dev/null | wc -l)"
echo "files in data/kb: $(ls "$TARGET_DIR"/kb_*.json 2>/dev/null | wc -l)"
echo "moved this run: $moved"
