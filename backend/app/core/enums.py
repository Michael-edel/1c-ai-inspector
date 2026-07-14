from enum import StrEnum


class Environment(StrEnum):
    SANDBOX = "sandbox"
    TEST = "test"


class ToolMode(StrEnum):
    READ_ONLY = "read-only"
    CONDITIONAL_WRITE = "conditional-write"
    WRITE = "write"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SideEffect(StrEnum):
    MODIFIES_SOURCE_CODE = "modifies_source_code"
    MODIFIES_METADATA = "modifies_metadata"
    MODIFIES_GIT = "modifies_git"
    MODIFIES_WORKSPACE = "modifies_workspace"
    UPDATES_INFORMATION_BASE = "updates_information_base"
    EXECUTES_EXTERNAL_CODE = "executes_external_code"
    NETWORK_WRITE = "network_write"
    CREATES_ARTIFACT = "creates_artifact"
    CHANGES_RUNTIME_STATE = "changes_runtime_state"


class TaskStatus(StrEnum):
    CREATED = "created"
    DISCOVERING = "discovering"
    ANALYZING = "analyzing"
    REPORTING = "reporting"
    # Retained so tasks created by pre-v0.1 deployments can still be recovered.
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PatchStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    CHECKPOINTED = "checkpointed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class SandboxExecutionStatus(StrEnum):
    CREATED = "created"
    PREPARING = "preparing"
    PREPARED = "prepared"
    APPLYING = "applying"
    VALIDATING = "validating"
    TESTING = "testing"
    AWAITING_ACCEPTANCE = "awaiting_acceptance"
    ROLLBACK_REQUIRED = "rollback_required"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
