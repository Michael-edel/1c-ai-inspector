#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/1c-ai-inspector}"
WITH_KEYCLOAK="${WITH_KEYCLOAK:-1}"
cd "$PROJECT_DIR"

declare -A values=()
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  values["$key"]="$value"
done < .env

declare -A minimums=(
  [POSTGRES_ADMIN_PASSWORD]=24
  [MIGRATION_DB_PASSWORD]=24
  [RUNTIME_DB_PASSWORD]=24
  [MODEL_API_KEY]=16
  [INSPECTOR_PACKAGE_SIGNING_SECRET]=32
)
if [[ "${values[INSPECTOR_AUTH_MODE]:-}" != "jwks" ]]; then
  minimums[INSPECTOR_AUTH_SECRET]=32
fi
if [[ "${values[MCP_TRANSPORT]:-}" == "bridge" ]]; then
  minimums[MCP_BRIDGE_TOKEN]=16
fi
if [[ "$WITH_KEYCLOAK" == "1" ]]; then
  minimums[KEYCLOAK_DB_PASSWORD]=24
  minimums[KEYCLOAK_ADMIN_PASSWORD]=24
fi

declare -A seen=()
failures=()
for key in "${!minimums[@]}"; do
  value="${values[$key]:-}"
  if [[ -z "$value" ]]; then
    failures+=("missing:$key")
    continue
  fi
  if [[ "$value" =~ (replace-with|change-me|example|your-|password123) ]]; then
    failures+=("placeholder:$key")
  fi
  if (( ${#value} < minimums[$key] )); then
    failures+=("short:$key")
  fi
  if [[ -n "${seen[$value]+x}" ]]; then
    failures+=("duplicate:$key:${seen[$value]}")
  else
    seen["$value"]="$key"
  fi
done

if (( ${#failures[@]} > 0 )); then
  printf 'Production secret audit failed without printing values: %s\n' "$(IFS=', '; echo "${failures[*]}")" >&2
  exit 1
fi

echo 'Production secret audit passed: required secrets are configured, sufficiently long and not duplicated. Values were not printed.'
