from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.mcp.policy import PolicyProvider
from app.models import Base, NormalizedTool
from app.services.mcp_discovery import McpDiscoveryService


def test_discovery_retires_tools_missing_from_current_server(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read A: {name: raw, category: bsl.read, mode: read-only}\n"
        "  Read B: {name: raw, category: code.search, mode: read-only}\n",
        encoding="utf-8",
    )
    snapshot = PolicyProvider(policy_path).load()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            NormalizedTool(
                id="tool_stale",
                original_name="Read B",
                normalized_name="read_b",
                category="code.search",
                mode="read-only",
                risk_level="low",
                side_effects_json="[]",
                contract_json="{}",
                policy_version="1.0.0",
                toolset_checksum="stale",
                publication_status="published",
            )
        )
        session.commit()
        McpDiscoveryService(session, snapshot, "http://mcp.test").persist(
            [snapshot.normalized_tools["read_a"]]
        )
        stale = session.get(NormalizedTool, "tool_stale")
        assert stale is not None
        assert stale.publication_status == "retired"
