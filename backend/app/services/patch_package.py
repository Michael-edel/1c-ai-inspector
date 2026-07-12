"""Build a portable proposal package entirely in memory."""

from io import BytesIO
from json import dumps, loads
from zipfile import ZIP_DEFLATED, ZipFile

from app.models import PatchProposal


def build_patch_package(proposal: PatchProposal) -> bytes:
    manifest = {
        "schemaVersion": "v0.3",
        "proposalId": proposal.id,
        "projectId": proposal.project_id,
        "title": proposal.title,
        "summary": proposal.summary,
        "status": proposal.status,
        "targetEnvironment": proposal.target_environment,
        "sourceRevision": proposal.source_revision,
        "files": loads(proposal.files_json),
        "impact": loads(proposal.impact_json),
        "checkpointRef": proposal.checkpoint_ref,
        "applyAllowed": False,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("proposal.diff", proposal.diff_text or "")
        archive.writestr(
            "README.txt",
            "This is a proposal-only package. It does not apply changes to 1C, the workspace, or Git.\n",
        )
    return buffer.getvalue()
