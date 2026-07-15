#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-https://inspector.michael.kz}"
MINIMUM_TOOLS="${MINIMUM_TOOLS:-10}"

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
costs = request("/api/v1/system/costs")
cost_estimate = request("/api/v1/system/cost-estimate")
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
for forbidden_tool in ("execute_query", "get_event_log"):
    if forbidden_tool in published:
        raise SystemExit(f"Forbidden {forbidden_tool} tool is published")
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
if costs.get("currency") != "KZT" or costs.get("estimatedCostKzt", -1) < 0 or costs.get("usdKztRate", 0) <= 0:
    raise SystemExit("Production model cost accounting is invalid")
pricing = costs.get("pricing", {})
if (pricing.get("model"), pricing.get("inputPer1M"), pricing.get("cachedInputPer1M"), pricing.get("outputPer1M")) != ("gpt-5.6-luna", 1, 0.1, 6):
    raise SystemExit("Production GPT-5.6 Luna pricing does not match the configured public tariff")
if cost_estimate.get("model") != "gpt-5.6-luna" or cost_estimate.get("currency") != "KZT" or cost_estimate.get("estimateType") != "upper-bound" or cost_estimate.get("estimatedCostKzt", 0) <= 0:
    raise SystemExit("Production preflight cost confirmation estimate is invalid")
if len(projects) < 1:
    raise SystemExit("No synchronized projects are available")
for item in history:
    if any(key in item for key in ("request", "requestJson", "result", "resultJson")):
        raise SystemExit("Task history exposes forbidden property")

print(
    "Production monitor passed: "
    f"health=ok readiness=ready discoveredTools={len(discovered)} "
    f"projects={len(projects)} taskHistory={len(history)} "
    f"traffic={traffic.get('accountedBytes')}/{traffic.get('hardLimitBytes')} "
    f"modelCostKzt={costs.get('estimatedCostKzt')}."
)
PY
