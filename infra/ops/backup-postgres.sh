#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/1c-ai-inspector}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/1c-ai-inspector}"
KEEP_DAYS="${KEEP_DAYS:-14}"

if ! [[ "$KEEP_DAYS" =~ ^[0-9]+$ ]]; then
  echo "KEEP_DAYS must be a non-negative integer" >&2
  exit 2
fi

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

compose=(
  docker compose --env-file .env
  -f docker-compose.yml
  -f docker-compose.production.yml
  -f docker-compose.keycloak.production.yml
  -f docker-compose.edge.production.yml
)

dump_service() {
  local service="$1"
  local prefix="$2"
  local stamp
  local final_path
  local temp_path

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  final_path="$BACKUP_DIR/${prefix}-${stamp}.dump"
  temp_path="${final_path}.tmp"

  "${compose[@]}" exec -T "$service" sh -lc \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$temp_path"
  test -s "$temp_path"
  cat "$temp_path" | "${compose[@]}" exec -T "$service" pg_restore --list >/dev/null
  mv "$temp_path" "$final_path"
  echo "Created $final_path"
}

dump_service postgres inspector-postgres
dump_service keycloak-db inspector-keycloak

find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -mtime "+$KEEP_DAYS" -delete
