#!/usr/bin/env bash
set -euo pipefail

: "${MIGRATION_DB_USER:?MIGRATION_DB_USER is required}"
: "${MIGRATION_DB_PASSWORD:?MIGRATION_DB_PASSWORD is required}"
: "${RUNTIME_DB_USER:?RUNTIME_DB_USER is required}"
: "${RUNTIME_DB_PASSWORD:?RUNTIME_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v migration_user="$MIGRATION_DB_USER" \
  -v migration_password="$MIGRATION_DB_PASSWORD" \
  -v runtime_user="$RUNTIME_DB_USER" \
  -v runtime_password="$RUNTIME_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migration_user', :'migration_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_user')\gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'runtime_user', :'runtime_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'runtime_user')\gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'migration_user')\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'runtime_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO %I', :'migration_user', :'runtime_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I', :'migration_user', :'runtime_user')\gexec
SQL
