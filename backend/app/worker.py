import json
import logging
import os
import socket
import time
import asyncio
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.executor import AgentExecutionError, execute_agent
from app.agents.registry import AgentRegistry
from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.db.session import get_session_factory
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicyProvider
from app.modeling import OpenAICompatibleAdapter
from app.models import Agent, Task, TaskEvent, ToolCall
from app.services.audit import AuditRecorder
from app.services.findings import persist_findings
from app.services.retrieval import RetrievalError, retrieve_task_context, tool_call_fingerprint
from app.services.task_cancellation import finalize_task_cancellation
from app.services.task_state import validate_transition

logger = logging.getLogger(__name__)


def recover_stale_tasks(session, lease_timeout_sec: int) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - lease_timeout_sec
    cutoff_dt = datetime.fromtimestamp(cutoff, timezone.utc)
    stale_tasks = session.scalars(
        select(Task)
        .where(
            Task.status == TaskStatus.RUNNING.value,
            Task.heartbeat_at.is_not(None),
            Task.heartbeat_at < cutoff_dt,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for task in stale_tasks:
        task.status = TaskStatus.QUEUED.value
        release_task_lease(task)
        task.last_error_code = "WORKER_LEASE_EXPIRED"
        AuditRecorder(session).record_event(
            task.id,
            "task_recovered",
            {"reason": "WORKER_LEASE_EXPIRED", "attempt": task.attempt},
        )
    return len(stale_tasks)


def release_task_lease(task: Task) -> None:
    task.locked_by = None
    task.locked_at = None
    task.heartbeat_at = None


def load_completed_tool_calls(session, task_id: str) -> dict[str, dict[str, object]]:
    cache: dict[str, dict[str, object]] = {}
    rows = session.scalars(
        select(ToolCall)
        .where(ToolCall.task_id == task_id, ToolCall.status == "completed")
        .order_by(ToolCall.created_at)
    ).all()
    for row in rows:
        try:
            arguments = json.loads(row.input_json)
            output = json.loads(row.output_json) if row.output_json else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(arguments, dict):
            continue
        cache[tool_call_fingerprint(row.tool_name, arguments)] = {
            "toolName": row.tool_name,
            "input": arguments,
            "output": output if isinstance(output, dict) else {},
            "status": row.status,
            "durationMs": row.duration_ms,
        }
    return cache


def persist_tool_call(session, task_id: str, call: dict[str, object]) -> None:
    with session.begin():
        AuditRecorder(session).record_tool_call(
            task_id,
            call["toolName"],
            "read-only",
            call["input"],
            call.get("output"),
            call["status"],
            call["durationMs"],
            call.get("errorCode"),
        )
    call["persisted"] = True


def record_retrieval_calls(session, task_id: str, calls: list[dict[str, object]]) -> None:
    reused_count = 0
    for call in calls:
        if call.get("reused"):
            reused_count += 1
        if call.get("persisted") or call.get("reused"):
            continue
        AuditRecorder(session).record_tool_call(
            task_id,
            call["toolName"],
            "read-only",
            call["input"],
            call.get("output"),
            call["status"],
            call["durationMs"],
            call.get("errorCode"),
        )
    if reused_count:
        AuditRecorder(session).record_event(
            task_id,
            "tool_call_reused",
            {"count": reused_count, "reason": "IDEMPOTENT_RETRY"},
        )


def refresh_task_heartbeat(session, task_id: str) -> bool:
    task = session.get(Task, task_id)
    if task is None or task.status != TaskStatus.RUNNING.value or task.cancel_requested:
        return False
    task.heartbeat_at = datetime.now(timezone.utc)
    return True


def task_allows_next_tool(session, task_id: str) -> bool:
    try:
        allowed = refresh_task_heartbeat(session, task_id)
        session.commit()
        return allowed
    except Exception:
        session.rollback()
        raise


def heartbeat_loop(task_id: str, interval_sec: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(interval_sec):
        heartbeat_session = get_session_factory()()
        try:
            with heartbeat_session.begin():
                if not refresh_task_heartbeat(heartbeat_session, task_id):
                    return
        except Exception:
            logger.exception("Worker heartbeat refresh failed", extra={"task_id": task_id})
        finally:
            heartbeat_session.close()


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
    if task.cancel_requested:
        finalize_task_cancellation(session, task, actor="worker")
        session.flush()
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
    task_id: str | None = None
    completed_calls: dict[str, dict[str, object]] = {}
    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None
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
            if task.cancel_requested:
                finalize_task_cancellation(session, task, actor="worker")
                return True
            agent = session.get(Agent, task.agent_id)
            if agent is None:
                raise AgentExecutionError("AGENT_NOT_FOUND")
            agent_code = agent.code
            request_json = task.request_json
            completed_calls = load_completed_tool_calls(session, task_id)
        settings = get_settings()
        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            args=(task_id, settings.worker_heartbeat_interval_sec, heartbeat_stop),
            name=f"task-heartbeat-{task_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        definition = AgentRegistry().get(agent_code)
        snapshot = PolicyProvider(settings.mcp_policy_path).load()
        try:
            request = json.loads(request_json)
            async def run_retrieval():
                connector = McpConnector(
                    str(settings.mcp_server_url),
                    snapshot,
                    transport_mode=settings.mcp_transport,
                    access_token=settings.mcp_bridge_token,
                )
                try:
                    return await retrieve_task_context(
                        request,
                        definition,
                        snapshot,
                        connector,
                        settings.max_tool_calls,
                        before_tool_call=lambda: task_allows_next_tool(session, task_id),
                        completed_calls=completed_calls,
                        on_tool_call=lambda call: persist_tool_call(session, task_id, call),
                    )
                finally:
                    await connector.close()

            retrieval = asyncio.run(run_retrieval())
        except (RetrievalError, ToolNotAllowedError, ValueError) as exc:
            if isinstance(exc, RetrievalError) and exc.calls:
                with session.begin():
                    record_retrieval_calls(session, task_id, exc.calls)
            if isinstance(exc, RetrievalError) and exc.code == "TASK_CANCELLED_BY_USER":
                with session.begin():
                    task = session.get(Task, task_id)
                    if task is not None and task.status == TaskStatus.RUNNING.value:
                        finalize_task_cancellation(session, task, actor="worker")
                return True
            if isinstance(exc, RetrievalError) and exc.code == "NON_IDEMPOTENT_RETRY_BLOCKED":
                raise AgentExecutionError(exc.code) from exc
            raise AgentExecutionError("RETRIEVAL_FAILED") from exc
        with session.begin():
            task = session.get(Task, task_id)
            if task is None:
                raise AgentExecutionError("TASK_NOT_FOUND")
            if task.cancel_requested:
                finalize_task_cancellation(session, task, actor="worker")
                return True
            record_retrieval_calls(session, task_id, retrieval.calls)
        with session.begin():
            task = session.get(Task, task_id)
            if task is None:
                raise AgentExecutionError("TASK_NOT_FOUND")
            if task.cancel_requested:
                finalize_task_cancellation(session, task, actor="worker")
                return True
            report = execute_agent(
                session,
                task,
                definition,
                settings,
                OpenAICompatibleAdapter(settings),
                retrieval.context,
                retrieval.calls,
            )
            validate_transition(TaskStatus.RUNNING.value, report.status)
            task.status = report.status
            release_task_lease(task)
            task.result_json = report.model_dump_json(by_alias=True)
            persist_findings(session, report)
            AuditRecorder(session).record_event(task_id, "task_completed", {"agent": agent_code})
    except AgentExecutionError as exc:
        with session.begin():
            task = session.get(Task, task_id)
            if task is not None:
                if task.cancel_requested:
                    finalize_task_cancellation(session, task, actor="worker")
                else:
                    task.status = TaskStatus.FAILED.value
                    task.last_error_code = exc.code
                    release_task_lease(task)
                    task.result_json = json.dumps({"status": "failed", "errorCode": exc.code})
                    AuditRecorder(session).record_event(task_id, "task_failed", {"errorCode": exc.code})
        return True
    except Exception:
        session.rollback()
        if task_id is not None:
            with session.begin():
                task = session.get(Task, task_id)
                if task is not None and task.cancel_requested and task.status == TaskStatus.RUNNING.value:
                    finalize_task_cancellation(session, task, actor="worker")
                    return True
        logger.exception("Worker failed while processing a task")
        return False
    finally:
        if heartbeat_thread is not None:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
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
