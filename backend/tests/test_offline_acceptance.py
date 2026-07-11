import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.registry import AgentRegistry
from app.core.config import get_settings
from app.mcp.connector import McpConnector
from app.mcp.policy import PolicyProvider
from app.modeling import ModelResult
from app.models import Base, ModelUsage, Project, Task
from app.services.findings import persist_findings
from app.services.mcp_discovery import McpDiscoveryService
from app.services.project_sync import sync_projects
from app.services.retrieval import retrieve_task_context


class FakeModel:
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        envelope = json.loads(messages[-1]["content"].split("Task envelope:\n", 1)[1])
        report = {
            "taskId": envelope["taskId"], "status": "completed",
            "summary": "Offline acceptance passed", "findings": [],
            "objectsReviewed": ["Catalog.Items"], "validation": {"readOnly": True},
            "toolUsage": {"calls": 1, "durationMs": 1},
            "modelUsage": {"inputTokens": 10, "outputTokens": 8, "estimatedCost": 0},
            "limitations": [], "nextActions": [],
        }
        return ModelResult(json.dumps(report), 10, 8)


def test_offline_acceptance_covers_mcp_projects_retrieval_and_report(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read Source: {name: raw, category: bsl.read, mode: read-only}\n"
        "  List Projects: {name: raw, category: metadata.read, mode: read-only}\n",
        encoding="utf-8",
    )
    snapshot = PolicyProvider(policy_path).load()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "Read Source"}, {"name": "List Projects"}]}})
        name = body["params"]["name"]
        if name == "List Projects":
            payload = {"projects": [{"id": "demo", "name": "Demo", "environment": "sandbox", "capabilities": ["bsl.read"]}]}
        else:
            payload = {"content": [{"type": "text", "text": "Catalog.Items source"}]}
        if name == "List Projects":
            result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        else:
            result = payload
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async def mcp_flow() -> tuple[set[str], int, list[dict[str, object]]]:
        connector = McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler))
        try:
            tools = await connector.discover_tools()
            with Session(engine) as sync_session:
                McpDiscoveryService(sync_session, snapshot, "http://mcp.test").persist(tools)
                projects = await sync_projects(sync_session, connector, "list_projects", "http://mcp.test")
            retrieval = await retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {"object": "Catalog.Items"}}]},
                AgentRegistry().get("1c_code_assistant"), snapshot, connector,
            )
            return {tool.name for tool in tools}, projects, retrieval.context
        finally:
            await connector.close()

    tools, projects, context = asyncio.run(mcp_flow())
    assert tools == {"read_source", "list_projects"}
    assert projects == 1
    assert context[0]["source"] == "MCP"

    with Session(engine) as session:
        project = session.scalars(select(Project)).one()
        task = Task(id="tsk_offline", project_id=project.id, agent_id="agt_offline", status="running", request_json=json.dumps({"text": "inspect"}), available_at=datetime.now(timezone.utc))
        session.add(task)
        session.commit()
        report = execute_agent(session, task, AgentRegistry().get("1c_code_assistant"), get_settings(), FakeModel(), context)
        persist_findings(session, report)
        session.commit()
        assert report.status == "completed"
        assert session.scalars(select(ModelUsage).where(ModelUsage.task_id == task.id)).one().output_tokens == 8
