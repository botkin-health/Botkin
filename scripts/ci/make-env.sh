#!/usr/bin/env bash
# Формирует копию .env с переопределением заданных ключей.
#   scripts/ci/make-env.sh <base.env> <overrides.env> > dev.env
# Ключи из overrides перекрывают base; новые — добавляются. Комментарии base сохраняются.
# Реальные секреты в git НЕ коммитим (.env* уже в .gitignore).
set -euo pipefail

BASE="${1:?укажи base .env}"
OVERRIDES="${2:?укажи overrides .env}"
[ -f "$BASE" ]      || { echo "❌ base не найден: $BASE" >&2; exit 1; }
[ -f "$OVERRIDES" ] || { echo "❌ overrides не найден: $OVERRIDES" >&2; exit 1; }

override_keys="$(grep -vE '^[[:space:]]*(#|$)' "$OVERRIDES" | cut -d= -f1)"

# 1) строки base, кроме переопределённых ключей (комментарии/пустые — сохраняем)
while IFS= read -r line; do
  key="${line%%=*}"
  printf '%s\n' "$override_keys" | grep -qxF "$key" && continue
  printf '%s\n' "$line"
done < "$BASE"

# 2) override-строки
grep -vE '^[[:space:]]*(#|$)' "$OVERRIDES"
