from app.agents.registry import AgentRegistry
from app.mcp.policy import PolicySnapshot
from app.services.readiness import ReadinessReport, ReadinessGate


def required_agent_capabilities() -> dict[str, set[str]]:
    return {
        definition.code: set(definition.required_capabilities)
        for definition in AgentRegistry().list()
    }


def evaluate_capabilities(
    snapshot: PolicySnapshot, discovered_tools: set[str] | None = None
) -> ReadinessReport:
    return ReadinessGate().evaluate(
        snapshot,
        discovered_tools,
        required_agent_capabilities(),
    )
