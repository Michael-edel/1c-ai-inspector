import json
import logging
import os
import socket
import time
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.agents.executor import AgentExecutionError, execute_agent
from app.agents.registry import AgentRegistry
from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.db.session import get_session_factory
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicyProvider
from app.modeling import OpenAICompatibleAdapter
from app.models import Agent, Task, TaskEvent
from app.services.audit import AuditRecorder
from app.services.findings import persist_findings
from app.services.retrieval import RetrievalError, retrieve_task_context
from app.services.task_state import validate_transition

logger = logging.getLogger(__name__)


def recover_stale_tasks(session, lease_timeout_sec: int) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - lease_timeout_sec
    cutoff_dt = datetime.fromtimestamp(cutoff, timezone.utc)
    result = session.execute(
        update(Task)
        .where(
            Task.status == TaskStatus.RUNNING.value,
            Task.heartbeat_at.is_not(None),
            Task.heartbeat_at < cutoff_dt,
        )
        .values(
            status=TaskStatus.QUEUED.value,
            locked_by=None,
            locked_at=None,
            heartbeat_at=None,
            last_error_code="WORKER_LEASE_EXPIRED",
        )
    )
    return result.rowcount


def claim_next_task(session, lease_timeout_sec: int = 600):
    """Atomically claim one PostgreSQL task without double processing."""
    now = datetime.now(timezone.utc)
    recover_stale_tasks(session, lease_timeout_sec)
    statement = (
        select(Task)
        .where(Task.status == TaskStatus.QUEUED.value, Task.available_at <= now)
        .order_by(Task.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = session.execute(statement).scalar_one_or_none()
    if task is None:
        return None
    validate_transition(task.status, TaskStatus.RUNNING.value)
    task.status = TaskStatus.RUNNING.value
    task.locked_by = socket.gethostname()
    task.locked_at = now
    task.heartbeat_at = now
    task.attempt += 1
    session.flush()
    return task


def process_one_task(lease_timeout_sec: int = 600) -> bool:
    session = get_session_factory()()
    try:
        with session.begin():
            task = claim_next_task(session, lease_timeout_sec)
            if task is None:
                return False
            task_id = task.id
            session.add(
                TaskEvent(
                    task_id=task_id,
                    event_type="task_started",
                    payload_json=json.dumps({"attempt": task.attempt}),
                )
            )
        with session.begin():
            task = session.get(Task, task_id)
            if task is None:
                raise AgentExecutionError("TASK_NOT_FOUND")
            agent = session.get(Agent, task.agent_id)
            if agent is None:
                raise AgentExecutionError("AGENT_NOT_FOUND")
            agent_code = agent.code
            request_json = task.request_json
        settings = get_settings()
        definition = AgentRegistry().get(agent_code)
        snapshot = PolicyProvider(settings.mcp_policy_path).load()
        try:
            request = json.loads(request_json)
            async def run_retrieval():
                connector = McpConnector(str(settings.mcp_server_url), snapshot)
                try:
                    return await retrieve_task_context(
                        request,
                        definition,
                        snapshot,
                        connector,
                        settings.max_tool_calls,
                    )
                finally:
                    await connector.close()

            retrieval = asyncio.run(run_retrieval())
        except (RetrievalError, ToolNotAllowedError, ValueError) as exc:
            if isinstance(exc, RetrievalError) and exc.calls:
                with session.begin():
                    for call in exc.calls:
                        AuditRecorder(session).record_tool_call(
                            task_id,
                            call["toolName"],
                            "read-only",
                            call["input"],
                            call["output"],
                            call["status"],
                            call["durationMs"],
                            call.get("errorCode"),
                        )
            raise AgentExecutionError("RETRIEVAL_FAILED") from exc
        with session.begin():
            for call in retrieval.calls:
                AuditRecorder(session).record_tool_call(
                    task_id,
                    call["toolName"],
                    "read-only",
                    call["input"],
                    call["output"],
                    call["status"],
                    call["durationMs"],
                    call.get("errorCode"),
                )
        with session.begin():
            task = session.get(Task, task_id)
            if task is None:
                raise AgentExecutionError("TASK_NOT_FOUND")
            report = execute_agent(
                session,
                task,
                definition,
                settings,
                OpenAICompatibleAdapter(settings),
                retrieval.context,
            )
            validate_transition(TaskStatus.RUNNING.value, report.status)
            task.status = report.status
            task.heartbeat_at = datetime.now(timezone.utc)
            task.result_json = report.model_dump_json(by_alias=True)
            persist_findings(session, report)
            AuditRecorder(session).record_event(task_id, "task_completed", {"agent": agent_code})
    except AgentExecutionError as exc:
        with session.begin():
            task = session.get(Task, task_id)
            if task is not None:
                task.status = TaskStatus.FAILED.value
                task.last_error_code = exc.code
                task.result_json = json.dumps({"status": "failed", "errorCode": exc.code})
                AuditRecorder(session).record_event(task_id, "task_failed", {"errorCode": exc.code})
        return True
    except Exception:
        session.rollback()
        logger.exception("Worker failed while processing a task")
        return False
    finally:
        session.close()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    once = os.getenv("WORKER_ONCE", "false").lower() == "true"
    interval = float(os.getenv("WORKER_POLL_INTERVAL_SEC", "1"))
    lease_timeout = int(os.getenv("WORKER_LEASE_TIMEOUT_SEC", "600"))
    while True:
        processed = process_one_task(lease_timeout)
        if once or not processed:
            if once:
                return
            time.sleep(interval)


if __name__ == "__main__":
    main()
