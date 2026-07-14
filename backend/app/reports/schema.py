from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SourceCoverage = Literal["full", "partial", "none", "unknown"]


class Evidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["source_range", "validation_error", "reference", "metadata_fact"]
    object_fqn: str = Field(alias="objectFqn", min_length=1)
    module: str = Field(min_length=1)
    method: str | None = None
    line_start: int | None = Field(default=None, alias="lineStart", ge=1)
    line_end: int | None = Field(default=None, alias="lineEnd", ge=1)
    excerpt: str | None = None
    description: str | None = None
    tool_call_id: str | None = Field(default=None, alias="toolCallId")


class Finding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    object_fqn: str = Field(alias="objectFqn", min_length=1)
    module: str = Field(min_length=1)
    method: str | None = None
    line_start: int | None = Field(default=None, alias="lineStart", ge=1)
    line_end: int | None = Field(default=None, alias="lineEnd", ge=1)
    description: str = Field(min_length=1)
    risk: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class ToolUsage(BaseModel):
    calls: int = Field(ge=0)
    duration_ms: int = Field(alias="durationMs", ge=0)

    model_config = ConfigDict(populate_by_name=True)


class ModelUsage(BaseModel):
    model: str = Field(default="unknown", min_length=1)
    input_tokens: int = Field(alias="inputTokens", ge=0)
    output_tokens: int = Field(alias="outputTokens", ge=0)
    cached_input_tokens: int = Field(default=0, alias="cachedInputTokens", ge=0)
    duration_ms: int = Field(default=0, alias="durationMs", ge=0)
    estimated_cost: float = Field(alias="estimatedCost", ge=0)
    pricing_source: str = Field(default="environment", alias="pricingSource", min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class StructuredReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(alias="taskId", min_length=1)
    status: Literal["completed", "failed", "cancelled"]
    summary: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    objects_reviewed: list[str] = Field(default_factory=list, alias="objectsReviewed")
    validation: dict[str, Any] = Field(default_factory=dict)
    source_coverage: SourceCoverage = Field(default="unknown", alias="sourceCoverage")
    tool_usage: ToolUsage = Field(alias="toolUsage")
    model_usage: ModelUsage = Field(alias="modelUsage")
    limitations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list, alias="nextActions")
