from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backend_container_does_not_run_as_root() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "COPY --chown=app:app" in dockerfile


def test_frontend_container_uses_lockfile_and_non_root_user() -> None:
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER node" in dockerfile
    assert "package-lock.json" in dockerfile
    assert "RUN npm ci" in dockerfile
