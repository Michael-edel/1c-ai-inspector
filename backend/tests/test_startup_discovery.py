import asyncio
from types import SimpleNamespace

from app import main


def test_auto_discovery_persists_tools_and_updates_readiness_state(monkeypatch) -> None:
    calls: list[object] = []

    class FakeConnector:
        def __init__(self, *args, **kwargs) -> None:
            calls.append(("connector", args, kwargs))

        async def discover_tools(self):
            return [SimpleNamespace(name="read_source")]

        async def close(self) -> None:
            calls.append("closed")

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    class FakeDiscovery:
        def __init__(self, db, snapshot, endpoint_url) -> None:
            calls.append(("service", db, snapshot, endpoint_url))

        def persist(self, tools) -> None:
            calls.append(("persist", tools))

    state = SimpleNamespace(
        settings=SimpleNamespace(
            mcp_server_url="http://mcp.test",
            mcp_transport="bridge",
            mcp_bridge_token="token",
        ),
        policy_snapshot=object(),
        discovered_tools={},
    )
    app = SimpleNamespace(state=state)

    monkeypatch.setattr(main, "McpConnector", FakeConnector)
    monkeypatch.setattr(main, "McpDiscoveryService", FakeDiscovery)
    monkeypatch.setattr(main, "get_session_factory", lambda: lambda: FakeSession())

    asyncio.run(main._auto_discover_mcp(app))

    assert state.discovered_tools == {"read_source": SimpleNamespace(name="read_source")}
    assert calls[0][0] == "connector"
    assert calls[1][0] == "service"
    assert calls[2][0] == "persist"
    assert calls[-1] == "closed"
