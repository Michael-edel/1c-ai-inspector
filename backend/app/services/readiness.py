from dataclasses import dataclass

from app.mcp.policy import PolicySnapshot


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    capabilities_status: str
    policy_loaded: bool
    normalized_toolset_built: bool
    only_read_only_tools_published: bool
    toolset_checksum: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capabilitiesStatus": self.capabilities_status,
            "policyLoaded": self.policy_loaded,
            "normalizedToolsetBuilt": self.normalized_toolset_built,
            "onlyReadOnlyToolsPublished": self.only_read_only_tools_published,
            "toolsetChecksum": self.toolset_checksum,
            "reasons": list(self.reasons),
        }


class ReadinessGate:
    def evaluate(self, snapshot: PolicySnapshot) -> ReadinessReport:
        reasons: list[str] = []
        only_read_only = len(snapshot.published_tools) == len(snapshot.normalized_tools)
        if not only_read_only:
            reasons.append("non_read_only_tool_published")

        if not snapshot.normalized_tools:
            reasons.append("no_tools_discovered")

        capabilities_status = "ready" if snapshot.normalized_tools else "not_discovered"
        status = "ready" if not reasons else "not_ready"
        return ReadinessReport(
            status=status,
            capabilities_status=capabilities_status,
            policy_loaded=True,
            normalized_toolset_built=True,
            only_read_only_tools_published=only_read_only,
            toolset_checksum=snapshot.toolset_checksum,
            reasons=tuple(reasons),
        )
