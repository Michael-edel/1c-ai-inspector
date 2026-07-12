"""Create proposal checkpoints without touching Git, files, or 1C."""

from hashlib import sha256


def create_checkpoint_ref(proposal_id: str, source_revision: str | None, diff_text: str | None) -> str:
    """Return a stable content reference for a proposal-only checkpoint."""
    content = f"{source_revision or ''}\0{diff_text or ''}".encode("utf-8")
    digest = sha256(content).hexdigest()
    return f"proposal-checkpoint:{proposal_id}:{digest}"
