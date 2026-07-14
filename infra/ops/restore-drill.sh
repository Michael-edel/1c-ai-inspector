#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/1c-ai-inspector}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/1c-ai-inspector}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-48}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"

if ! [[ "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] || (( MAX_AGE_HOURS == 0 )); then
  echo "MAX_AGE_HOURS must be a positive integer" >&2
  exit 2
fi

cd "$PROJECT_DIR"

latest_dump() {
  local prefix="$1"
  local path
  path="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${prefix}-*.dump" -printf '%T@ %p\n' | sort -nr | sed -n '1s/^[^ ]* //p')"
  if [[ -z "$path" ]]; then
    echo "No dump found for $prefix in $BACKUP_DIR" >&2
    exit 1
  fi
  printf '%s\n' "$path"
}

assert_fresh() {
  local path="$1"
  local now modified age max_age
  now="$(date +%s)"
  modified="$(stat -c '%Y' "$path")"
  age=$(( now - modified ))
  max_age=$(( MAX_AGE_HOURS * 3600 ))
  if (( age < 0 || age > max_age )); then
    echo "Backup is older than ${MAX_AGE_HOURS}h: $path" >&2
    exit 1
  fi
  test -s "$path"
}

restore_into_ephemeral_db() (
  local label="$1"
  local path="$2"
  local container="1c-ai-inspector-restore-drill-${label}-$$"
  local attempt

  docker run -d --rm --name "$container" \
    -e POSTGRES_PASSWORD=restore-drill \
    -e POSTGRES_DB=drill \
    "$POSTGRES_IMAGE" >/dev/null

  cleanup_container() {
    docker rm -f "$container" >/dev/null 2>&1 || true
  }
  # A subshell-local EXIT trap also runs when pg_restore or readiness checks fail.
  trap cleanup_container EXIT

  for attempt in $(seq 1 60); do
    # The official image exposes a temporary PostgreSQL server during initdb.
    # Wait for that init phase to finish before trusting pg_isready.
    if docker logs "$container" 2>&1 \
        | grep -Fq "PostgreSQL init process complete; ready for start up." \
      && docker exec "$container" pg_isready -U postgres -d drill >/dev/null 2>&1; then
      break
    fi
    if (( attempt == 60 )); then
      echo "Temporary PostgreSQL container did not become ready: $container" >&2
      docker logs "$container" >&2 || true
      exit 1
    fi
    sleep 1
  done

  cat "$path" | docker exec -i -e PGPASSWORD=restore-drill "$container" \
    pg_restore -U postgres -d drill --no-owner --no-privileges --exit-on-error --single-transaction
  echo "Restore drill passed for $label: $(basename "$path")"
)

postgres_dump="$(latest_dump inspector-postgres)"
keycloak_dump="$(latest_dump inspector-keycloak)"
assert_fresh "$postgres_dump"
assert_fresh "$keycloak_dump"
restore_into_ephemeral_db postgres "$postgres_dump"
restore_into_ephemeral_db keycloak "$keycloak_dump"

echo "Restore drill passed: latest application and Keycloak dumps restored into disposable databases; live services were not modified."
