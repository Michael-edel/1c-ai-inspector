"""Build and verify portable, signed proposal packages entirely in memory."""

import hashlib
import hmac
from io import BytesIO
from json import dumps, loads
from zipfile import ZIP_DEFLATED, ZipFile

from app.models import PatchProposal


def build_patch_package(proposal: PatchProposal, secret: str) -> bytes:
    diff = proposal.diff_text or ""
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
        "signatureAlgorithm": "HMAC-SHA256",
        "diffSha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
    }
    payload = _signature_payload(manifest, diff)
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("proposal.diff", diff)
        archive.writestr(
            "signature.json",
            dumps(
                {
                    "algorithm": "HMAC-SHA256",
                    "payloadSha256": hashlib.sha256(payload).hexdigest(),
                    "signature": signature,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr(
            "README.txt",
            "This is a proposal-only package. It does not apply changes to 1C, the workspace, or Git.\n",
        )
    return buffer.getvalue()


def verify_patch_package(package: bytes, secret: str, expected_proposal_id: str | None = None) -> dict[str, object]:
    try:
        with ZipFile(BytesIO(package)) as archive:
            manifest = loads(archive.read("manifest.json"))
            diff = archive.read("proposal.diff").decode("utf-8")
            signature = loads(archive.read("signature.json"))
    except (KeyError, UnicodeDecodeError, ValueError):
        return {"valid": False, "reason": "PACKAGE_FORMAT_INVALID"}
    if expected_proposal_id and manifest.get("proposalId") != expected_proposal_id:
        return {"valid": False, "reason": "PACKAGE_PROPOSAL_MISMATCH"}
    if manifest.get("diffSha256") != hashlib.sha256(diff.encode("utf-8")).hexdigest():
        return {"valid": False, "reason": "PACKAGE_DIFF_HASH_MISMATCH"}
    payload = _signature_payload(manifest, diff)
    expected_signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    valid = (
        signature.get("algorithm") == "HMAC-SHA256"
        and signature.get("payloadSha256") == hashlib.sha256(payload).hexdigest()
        and hmac.compare_digest(str(signature.get("signature", "")), expected_signature)
    )
    return {
        "valid": valid,
        "proposalId": manifest.get("proposalId"),
        "status": manifest.get("status"),
        "targetEnvironment": manifest.get("targetEnvironment"),
        "checkpointRef": manifest.get("checkpointRef"),
        "algorithm": "HMAC-SHA256",
        "reason": None if valid else "PACKAGE_SIGNATURE_INVALID",
    }


def _signature_payload(manifest: dict[str, object], diff: str) -> bytes:
    canonical = dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return canonical.encode("utf-8") + b"\0" + diff.encode("utf-8")
