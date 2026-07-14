from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_openapi_is_routed_to_backend_without_caching() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    assert 'header /openapi.json Cache-Control "no-store"' in caddyfile
    assert "reverse_proxy /openapi.json backend:8000" in caddyfile
