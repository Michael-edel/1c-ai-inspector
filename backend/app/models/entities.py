from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class McpServer(TimestampMixin, Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    server_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mcp_server_id: Mapped[str] = mapped_column(ForeignKey("mcp_servers.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    available_capabilities: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column()
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class TaskEvent(TimestampMixin, Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class ToolCall(TimestampMixin, Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text)
    result_size_chars: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    object_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    module: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str | None] = mapped_column(String(255))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)


class FindingStatusEvent(TimestampMixin, Base):
    __tablename__ = "finding_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)


class ModelUsage(TimestampMixin, Base):
    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(nullable=False, default=0)
    pricing_source: Mapped[str] = mapped_column(String(128), nullable=False, default="environment")
    response_checksum: Mapped[str | None] = mapped_column(String(64))


class NormalizedTool(TimestampMixin, Base):
    __tablename__ = "normalized_tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    side_effects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    contract_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    toolset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class PromptExecutionSnapshot(TimestampMixin, Base):
    __tablename__ = "prompt_execution_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    toolset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class PatchProposal(TimestampMixin, Base):
    __tablename__ = "patch_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    target_environment: Mapped[str] = mapped_column(String(32), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(128))
    diff_text: Mapped[str | None] = mapped_column(Text)
    files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    impact_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    checkpoint_ref: Mapped[str | None] = mapped_column(String(255))
    approval_note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    decision_role: Mapped[str | None] = mapped_column(String(32))
    source_validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    source_validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_validated_at: Mapped[datetime | None] = mapped_column()
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unvalidated")
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    validated_at: Mapped[datetime | None] = mapped_column()


class PatchEvent(TimestampMixin, Base):
    __tablename__ = "patch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("patch_proposals.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class PatchPackageVersion(TimestampMixin, Base):
    __tablename__ = "patch_package_versions"
    __table_args__ = (UniqueConstraint("proposal_id", "version", name="uq_patch_package_proposal_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("patch_proposals.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    package_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
