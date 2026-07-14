from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_openapi_is_routed_to_backend_without_caching() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    assert 'header /openapi.json Cache-Control "no-store"' in caddyfile
    assert "reverse_proxy /openapi.json backend:8000" in caddyfile


def test_application_edge_enforces_browser_security_headers() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile
    assert "Content-Security-Policy \"default-src 'self';" in caddyfile
    assert "frame-ancestors 'none'" in caddyfile
    assert "object-src 'none'" in caddyfile
    assert "font-src 'self'" in caddyfile
    assert "style-src 'self'" in caddyfile
    assert "fonts.googleapis.com" not in caddyfile
    assert "fonts.gstatic.com" not in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'X-Frame-Options "DENY"' in caddyfile
