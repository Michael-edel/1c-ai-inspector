"""Environment and risk policy for proposal approval."""


class PatchPolicyError(ValueError):
    """Raised when a proposal cannot be approved in the current contour."""


def authorize_environment(
    role: str,
    target_environment: str,
    app_environment: str,
    impacts: list[dict[str, object]],
) -> None:
    if target_environment != app_environment:
        raise PatchPolicyError("PATCH_ENVIRONMENT_MISMATCH")
    if target_environment not in {"sandbox", "test"}:
        raise PatchPolicyError("PATCH_ENVIRONMENT_NOT_ALLOWED")
    if target_environment == "test" and role != "owner":
        raise PatchPolicyError("PATCH_TEST_OWNER_REQUIRED")
    if any(item.get("risk") == "candidate" for item in impacts) and role != "owner":
        raise PatchPolicyError("PATCH_CANDIDATE_OWNER_REQUIRED")
