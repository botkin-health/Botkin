#!/usr/bin/env bash
# Сверяет .env с манифестом обязательных ключей: каждый должен присутствовать
# и быть непустым. Любой пропуск → exit 1.
# Локальный хелпер: прогоняй на .env ПЕРЕД тем как класть его на сервер.
#   scripts/ci/check-required-env.sh <.env> [deploy/required-prod-env]
set -euo pipefail

ENV_FILE="${1:-.env}"
MANIFEST="${2:-deploy/required-prod-env}"

[ -f "$ENV_FILE" ] || { echo "❌ env-файл не найден: $ENV_FILE" >&2; exit 1; }
[ -f "$MANIFEST" ] || { echo "❌ манифест не найден: $MANIFEST" >&2; exit 1; }

missing=0
while IFS= read -r raw; do
  key="${raw%%#*}"
  key="$(printf '%s' "$key" | tr -d '[:space:]')"
  [ -z "$key" ] && continue
  # Точное совпадение имени ключа (awk, без regex-инъекции из манифеста).
  val="$(awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$ENV_FILE")"
  # Значение из одних пробелов считаем пустым.
  if [ -z "$(printf '%s' "$val" | tr -d '[:space:]')" ]; then
    echo "❌ отсутствует или пуст обязательный ключ: $key" >&2
    missing=1
  fi
done < "$MANIFEST"

[ "$missing" -eq 0 ] || { echo "❌ Гейт прод-env не пройден." >&2; exit 1; }
echo "✅ Все обязательные прод-ключи на месте."
