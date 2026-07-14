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


def request_raw(path):
    with urllib.request.urlopen(f"{base_url}{path}", timeout=20) as response:
        return response.read(), response.headers


def request(path):
    body, _ = request_raw(path)
    return json.loads(body)


root_body, root_headers = request_raw("/")
health_body, health_headers = request_raw("/health")
health = json.loads(health_body)
readiness = request("/api/v1/system/readiness")
policy = request("/api/v1/system/policy")
traffic = request("/api/v1/system/traffic")
projects = request("/api/v1/projects")
history = request("/api/v1/tasks")
discovered = policy.get("discoveredTools", [])
published = policy.get("publishedTools", [])

if "no-store" not in root_headers.get("Cache-Control", ""):
    raise SystemExit("Production HTML shell is cacheable")
if b"/@vite/client" in root_body or b"/src/main.tsx" in root_body:
    raise SystemExit("Production HTML exposes Vite development entrypoints")
if health.get("status") != "ok":
    raise SystemExit("Production health is not ok")
if base_url.lower().startswith("https://"):
    hsts = health_headers.get("Strict-Transport-Security", "")
    csp = health_headers.get("Content-Security-Policy", "")
    if "max-age=" not in hsts:
        raise SystemExit("Missing or invalid Strict-Transport-Security header")
    required_csp = ("default-src 'self'", "font-src 'self'", "style-src 'self'", "frame-ancestors 'none'", "object-src 'none'")
    if not all(directive in csp for directive in required_csp) or "https://" in csp or "http://" in csp:
        raise SystemExit("Missing or invalid Content-Security-Policy header")
if readiness.get("status") != "ready":
    raise SystemExit("Production readiness is not ready")
if len(discovered) < minimum_tools:
    raise SystemExit(f"Expected at least {minimum_tools} discovered tools")
if "execute_query" in published:
    raise SystemExit("Forbidden execute_query tool is published")
if (
    traffic.get("warningBytes") != 5_000_000_000
    or traffic.get("criticalBytes") != 8_000_000_000
    or traffic.get("hardLimitBytes") != 9_800_000_000
):
    raise SystemExit("Production traffic thresholds do not match 5/8/9.8 GB")
if traffic.get("level") not in {"normal", "warning", "critical", "blocked"}:
    raise SystemExit("Production traffic level is invalid")
if traffic.get("accountedBytes", 0) > traffic.get("hardLimitBytes", 0) or traffic.get("remainingBytes", -1) < 0:
    raise SystemExit("Production traffic counter exceeds its hard limit")
if len(projects) < 1:
    raise SystemExit("No synchronized projects are available")
for item in history:
    if any(key in item for key in ("request", "requestJson", "result", "resultJson")):
        raise SystemExit("Task history exposes forbidden property")

print(
    "Production monitor passed: "
    f"health=ok readiness=ready discoveredTools={len(discovered)} "
    f"projects={len(projects)} taskHistory={len(history)} "
    f"traffic={traffic.get('accountedBytes')}/{traffic.get('hardLimitBytes')}."
)
PY
