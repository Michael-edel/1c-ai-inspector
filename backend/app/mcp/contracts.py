from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskLevel, SideEffect, ToolMode


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    version: str = "1.0.0"
    mode: ToolMode
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    idempotent: bool = True
    side_effects: list[SideEffect] = Field(default_factory=list)
    timeout_sec: int = Field(default=30, ge=1, le=600)
    retries: int = Field(default=0, ge=0, le=3)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    write_conditions: list[str] = Field(default_factory=list)


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(alias="policyId")
    version: str
    tools: dict[str, ToolContract] = Field(default_factory=dict)
