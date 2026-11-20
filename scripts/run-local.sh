#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

mode="${1:-demo}"
if [[ "$mode" != demo && "$mode" != pilot ]]; then
  printf 'Usage: %s [demo|pilot]\n' "$0" >&2
  exit 2
fi
python="${COMPANY_AI_PYTHON:-.venv/bin/python}"
pgbin="$(pg_config --bindir)"
root="$PWD/data/processed/mvp-dev"
database="company_ai_$mode"
mkdir -p "$root/socket"
chmod 700 "$root" "$root/socket"
export PGHOST="$root/socket" PGPORT="${COMPANY_AI_LOCAL_PG_PORT:-55437}"

if [[ ! -f "$root/postgres/PG_VERSION" ]]; then
  "$pgbin/initdb" -D "$root/postgres" -A trust --encoding=UTF8 --locale=C > "$root/init.log"
fi
if ! "$pgbin/pg_ctl" -D "$root/postgres" status >/dev/null 2>&1; then
  "$pgbin/pg_ctl" -D "$root/postgres" -l "$root/postgres.log" \
    -o "-p $PGPORT -h '' -k '$PGHOST'" -w start
fi
if ! "$pgbin/pg_isready" -q -h "$PGHOST" -p "$PGPORT"; then
  printf 'The local PostgreSQL cluster is running with a different socket or port. Stop it before retrying.\n' >&2
  exit 1
fi
if [[ "$("$pgbin/psql" -XAtd postgres -c "SELECT count(*) FROM pg_roles WHERE rolname='company_ai_local'")" == 0 ]]; then
  "$pgbin/createuser" --no-superuser --no-createdb --no-createrole company_ai_local
fi
if [[ "$("$pgbin/psql" -XAtd postgres -c "SELECT count(*) FROM pg_database WHERE datname='$database'")" == 0 ]]; then
  "$pgbin/createdb" "$database"
fi

export COMPANY_AI_ADMIN_DATABASE_URL="dbname=$database"
"$python" -m company_ai.mvp.manage migrate
"$python" -m company_ai.mvp.manage grant-runtime company_ai_local
if [[ "$mode" == demo ]]; then
  "$python" -m company_ai.mvp.manage seed-demo
  export COMPANY_AI_DEMO=1
else
  export COMPANY_AI_DEMO=0 COMPANY_AI_SITE_COMPANY="${COMPANY_AI_SITE_COMPANY:-MAQSU}"
fi
export COMPANY_AI_DATABASE_URL="dbname=$database user=company_ai_local"
unset COMPANY_AI_ADMIN_DATABASE_URL
exec "$python" -m uvicorn company_ai.mvp.app:app_from_env --factory \
  --host 127.0.0.1 --port "${COMPANY_AI_HTTP_PORT:-8765}" --no-access-log
