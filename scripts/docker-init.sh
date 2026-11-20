#!/usr/bin/env bash
set -euo pipefail
psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
\getenv app_password COMPANY_AI_DB_APP_PASSWORD
CREATE ROLE company_ai_runtime LOGIN PASSWORD :'app_password' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
SQL
