from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentos.gateway.task_runtime import TaskRuntime
from agentos.session.models import AgentTaskRecord, AgentTaskStatus, SessionNode
from agentos.session.storage import SessionStorage


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncGenerator[SessionStorage, None]:
    s = SessionStorage(str(tmp_path / "test.db"))
    await s.connect()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_task_runtime_list_returns_newest_tasks(storage: SessionStorage) -> None:
    # Setup session
    session_key = "test_session"
    node = SessionNode(session_key=session_key)
    await storage.upsert_session(node)

    # Insert 105 tasks
    # 0-103 are "done", 104 is "running"
    for i in range(105):
        task = AgentTaskRecord(
            task_id=f"task-{i:03d}",
            session_key=session_key,
            agent_id="main",
            status=AgentTaskStatus.SUCCEEDED if i < 104 else AgentTaskStatus.RUNNING,
            created_at=1000 + i,
        )
        await storage.create_agent_task(task)

    # Setup TaskRuntime
    runtime = TaskRuntime(storage=storage, turn_handler=Mock())

    # List tasks
    tasks = await runtime.list(session_key=session_key)

    # Should return at most 100 tasks (default limit)
    assert len(tasks) == 100

    # The last task in the list should be the newest one (task-104)
    assert tasks[-1].task_id == "task-104"
    assert tasks[-1].status == AgentTaskStatus.RUNNING

    # The first task in the list should be task-005
    assert tasks[0].task_id == "task-005"
