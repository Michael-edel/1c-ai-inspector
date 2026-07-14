from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backend_container_does_not_run_as_root() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "COPY --chown=app:app" in dockerfile


def test_frontend_container_uses_lockfile_and_non_root_user() -> None:
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "FROM node:22-alpine AS build" in dockerfile
    assert "FROM nginxinc/nginx-unprivileged:" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "COPY --from=build /app/dist" in dockerfile
    assert "USER 101" in dockerfile
    assert "package-lock.json" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "npm run dev" not in dockerfile
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "proxy_pass http://backend:8000" in nginx
    server_headers = nginx.split("location /api/", maxsplit=1)[0]
    assert 'add_header Cache-Control "no-store" always;' in server_headers
    assert 'add_header Cache-Control "public, immutable";' in nginx


def test_frontend_fonts_are_bundled_without_remote_stylesheets() -> None:
    package = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    entrypoint = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert '"@fontsource/dm-mono"' in package
    assert '"@fontsource-variable/manrope"' in package
    assert 'import "@fontsource/dm-mono/latin-400.css"' in entrypoint
    assert 'import "@fontsource-variable/manrope/index.css"' in entrypoint
    assert "fonts.googleapis.com" not in styles
    assert "fonts.gstatic.com" not in styles


def test_linux_operations_scripts_are_exported_with_lf_endings() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "*.sh text eol=lf" in attributes.splitlines()
    for script in ROOT.glob("**/*.sh"):
        assert b"\r\n" not in script.read_bytes(), f"CRLF is not allowed in {script.relative_to(ROOT)}"
