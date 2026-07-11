import json
import logging
import os
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.enums import TaskStatus
from app.db.session import get_session_factory
from app.models import Task, TaskEvent

logger = logging.getLogger(__name__)


def claim_next_task(session):
    """Atomically claim one PostgreSQL task without double processing."""
    now = datetime.now(timezone.utc)
    statement = (
        select(Task)
        .where(Task.status == TaskStatus.CREATED.value, Task.available_at <= now)
        .order_by(Task.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = session.execute(statement).scalar_one_or_none()
    if task is None:
        return None
    task.status = TaskStatus.RUNNING.value
    task.locked_by = socket.gethostname()
    task.locked_at = now
    task.attempt += 1
    session.flush()
    return task


def process_one_task() -> bool:
    session = get_session_factory()()
    try:
        with session.begin():
            task = claim_next_task(session)
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
        # Agent execution is intentionally not enabled in this foundation slice.
        with session.begin():
            task = session.get(Task, task_id)
            if task is not None:
                task.status = TaskStatus.COMPLETED.value
                task.result_json = json.dumps({"status": "technical_task_completed"})
                session.add(
                    TaskEvent(
                        task_id=task_id,
                        event_type="task_completed",
                        payload_json='{"mode":"foundation"}',
                    )
                )
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
    while True:
        processed = process_one_task()
        if once or not processed:
            if once:
                return
            time.sleep(interval)


if __name__ == "__main__":
    main()
