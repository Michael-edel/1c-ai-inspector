#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-https://inspector.michael.kz}"
MINIMUM_TOOLS="${MINIMUM_TOOLS:-8}"

python3 - "$BASE_URL" "$MINIMUM_TOOLS" <<'PY'
import json
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
minimum_tools = int(sys.argv[2])


def request(path):
    with urllib.request.urlopen(f"{base_url}{path}", timeout=20) as response:
        return json.load(response)


health = request("/health")
readiness = request("/api/v1/system/readiness")
policy = request("/api/v1/system/policy")
projects = request("/api/v1/projects")
history = request("/api/v1/tasks")
discovered = policy.get("discoveredTools", [])
published = policy.get("publishedTools", [])

if health.get("status") != "ok":
    raise SystemExit("Production health is not ok")
if readiness.get("status") != "ready":
    raise SystemExit("Production readiness is not ready")
if len(discovered) < minimum_tools:
    raise SystemExit(f"Expected at least {minimum_tools} discovered tools")
if "execute_query" in published:
    raise SystemExit("Forbidden execute_query tool is published")
if len(projects) < 1:
    raise SystemExit("No synchronized projects are available")
for item in history:
    if any(key in item for key in ("request", "requestJson", "result", "resultJson")):
        raise SystemExit("Task history exposes forbidden property")

print(
    "Production monitor passed: "
    f"health=ok readiness=ready discoveredTools={len(discovered)} "
    f"projects={len(projects)} taskHistory={len(history)}."
)
PY
