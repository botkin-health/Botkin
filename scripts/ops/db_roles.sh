#!/usr/bin/env bash
# Включить рантайм-роли БД на стенде (ADR-0014). Запускать НА СЕРВЕРЕ после
# миграции rls02:
#
#   bash db_roles.sh /opt/botkin-dev botkin_dev_postgres     # дев
#   bash db_roles.sh /opt/botkin     healthvault_postgres    # прод — только по согласованию
#
# Что делает (идемпотентно):
#   1. Пароли HV_APP_DB_PASSWORD / HV_SYSTEM_DB_PASSWORD: берёт из .env стенда,
#      если их нет — генерирует и дописывает в .env.
#   2. ALTER ROLE hv_app / hv_system LOGIN PASSWORD … (через psql владельцем).
#   3. Пишет в .env APP_DATABASE_URL (hv_app) и SYSTEM_DATABASE_URL (hv_system).
#      Compose подставит APP_DATABASE_URL в DATABASE_URL бота при следующем up -d.
#
# Пароли в stdout не печатаются. Откат: убрать APP_DATABASE_URL и
# SYSTEM_DATABASE_URL из .env и `docker compose up -d` — бот вернётся на healthvault.
set -euo pipefail

STAND="${1:?путь стенда, например /opt/botkin-dev}"
PG="${2:?контейнер postgres, например botkin_dev_postgres}"
ENV_FILE="$STAND/.env"
[ -f "$ENV_FILE" ] || { echo "нет $ENV_FILE"; exit 1; }

get_env() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
set_env() {
  local key="$1" val="$2"
  if grep -qE "^$key=" "$ENV_FILE"; then
    # без sed -i с паролем в аргументах: переписываем файл через awk + env
    KEY="$key" VAL="$val" awk 'BEGIN{k=ENVIRON["KEY"]; v=ENVIRON["VAL"]} index($0, k"=")==1 {print k"="v; next} {print}' \
      "$ENV_FILE" > "$ENV_FILE.tmp" && cat "$ENV_FILE.tmp" > "$ENV_FILE" && rm -f "$ENV_FILE.tmp"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}
gen() { openssl rand -hex 24; }

# Пароль идёт в URL и в SQL-литерал — допускаем только [A-Za-z0-9]. Старый
# HV_APP_DB_PASSWORD со спецсимволами перегенерируется (роль hv_app до ADR-0014
# не использовалась, менять её пароль безопасно).
safe() { [[ -n "$1" && "$1" =~ ^[A-Za-z0-9]+$ ]]; }
APP_PW="$(get_env HV_APP_DB_PASSWORD)";    safe "$APP_PW" || { APP_PW="$(gen)"; set_env HV_APP_DB_PASSWORD "$APP_PW"; }
SYS_PW="$(get_env HV_SYSTEM_DB_PASSWORD)"; safe "$SYS_PW" || { SYS_PW="$(gen)"; set_env HV_SYSTEM_DB_PASSWORD "$SYS_PW"; }

DB="$(get_env POSTGRES_DB)";   DB="${DB:-healthvault}"
OWNER="$(get_env POSTGRES_USER)"; OWNER="${OWNER:-healthvault}"

# Пароли — через stdin (printf — builtin, в `ps` не светится). Hex без кавычек.
{
  printf "ALTER ROLE hv_app    LOGIN PASSWORD '%s';\n" "$APP_PW"
  printf "ALTER ROLE hv_system LOGIN PASSWORD '%s';\n" "$SYS_PW"
} | docker exec -i "$PG" psql -v ON_ERROR_STOP=1 -U "$OWNER" -d "$DB" -q

set_env APP_DATABASE_URL    "postgresql://hv_app:${APP_PW}@postgres:5432/${DB}"
set_env SYSTEM_DATABASE_URL "postgresql://hv_system:${SYS_PW}@postgres:5432/${DB}"
chmod 600 "$ENV_FILE"

docker exec "$PG" psql -U "$OWNER" -d "$DB" -Atc \
  "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname IN ('hv_app','hv_system') ORDER BY 1"
echo "✅ роли включены, APP_DATABASE_URL / SYSTEM_DATABASE_URL в $ENV_FILE. Дальше: docker compose up -d"
