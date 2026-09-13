from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agentos.engine.subagent import (
    SubagentHandle,
    SubagentManager,
    SubagentRegistry,
    SubagentSpec,
)


@pytest.mark.asyncio
async def test_subagent_registry_abort_only_running() -> None:
    registry = SubagentRegistry()

    async def _long_task() -> str:
        await asyncio.sleep(10)
        return "finished"

    task = asyncio.create_task(_long_task())
    handle = SubagentHandle(
        run_id="run-1",
        label="test",
        task=task,
        status="running",
    )
    registry.register(handle)

    # 1. Abort a running task
    assert registry.abort("run-1") is True
    assert handle.status == "aborted"
    assert handle.completed_at is not None
    orig_completed_at = handle.completed_at

    # 2. Calling abort on an already aborted task returns False and preserves completed_at
    assert registry.abort("run-1") is False
    assert handle.status == "aborted"
    assert handle.completed_at == orig_completed_at

    # 3. Calling abort on a completed (done) task returns False and preserves result/status
    async def _dummy() -> str:
        return "ok"

    done_task = asyncio.create_task(_dummy())
    await done_task
    done_handle = SubagentHandle(
        run_id="run-2",
        label="completed-task",
        task=done_task,
        status="done",
        result="success-data",
        completed_at=100.0,
    )
    registry.register(done_handle)

    assert registry.abort("run-2") is False
    assert done_handle.status == "done"
    assert done_handle.result == "success-data"
    assert done_handle.completed_at == 100.0

    # 4. Unknown run_id returns False
    assert registry.abort("non-existent") is False


@pytest.mark.asyncio
async def test_subagent_registry_cleanup_orphans_evicts_done_parents() -> None:
    registry = SubagentRegistry()

    async def _parent() -> None:
        pass

    parent_task = asyncio.create_task(_parent())
    await parent_task  # Parent task is done

    async def _child() -> str:
        await asyncio.sleep(10)
        return "child"

    child_task = asyncio.create_task(_child())
    child_handle = SubagentHandle(
        run_id="child-1",
        label="child",
        task=child_task,
        status="running",
    )
    registry.register(child_handle, parent_task=parent_task)

    assert "child-1" in registry._parent_tasks
    aborted = registry.cleanup_orphans()
    assert aborted == ["child-1"]
    assert child_handle.status == "aborted"
    # Done parent task must be evicted to prevent memory leak
    assert "child-1" not in registry._parent_tasks


@pytest.mark.asyncio
async def test_subagent_registry_cleanup_orphans_evicts_finished_child() -> None:
    registry = SubagentRegistry()

    async def _parent() -> None:
        await asyncio.sleep(10)

    parent_task = asyncio.create_task(_parent())

    async def _child() -> str:
        return "done"

    child_task = asyncio.create_task(_child())
    await child_task
    child_handle = SubagentHandle(
        run_id="child-2",
        label="child-done",
        task=child_task,
        status="done",
    )
    registry.register(child_handle, parent_task=parent_task)

    assert "child-2" in registry._parent_tasks
    # Parent is still running, but child has completed; cleanup_orphans should evict it
    aborted = registry.cleanup_orphans()
    assert aborted == []
    assert "child-2" not in registry._parent_tasks

    parent_task.cancel()
    try:
        await parent_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_subagent_manager_spawn_wires_parent_task() -> None:
    manager = SubagentManager()
    current = asyncio.current_task()
    assert current is not None

    class MockAgent:
        async def run_turn(self, task: str) -> Any:
            yield type("Event", (), {"kind": "text_delta", "text": "result"})()
            yield type("Event", (), {"kind": "done"})()

    def factory(spec: SubagentSpec, depth: int) -> MockAgent:
        return MockAgent()

    spec = SubagentSpec(task="test task", label="test label")
    handle = await manager.spawn(spec, factory)

    assert handle.parent_task_id == id(current)
    assert handle.run_id in manager.registry._parent_tasks
    assert manager.registry._parent_tasks[handle.run_id] is current

    # Wait for subagent task to finish
    await handle.task
    assert handle.status == "done"
    assert handle.result == "result"


def test_subagent_registry_save_and_load_state_utf8(tmp_path: Path) -> None:
    registry = SubagentRegistry()

    async def _dummy() -> str:
        return ""

    loop = asyncio.new_event_loop()
    task = loop.create_task(_dummy())

    handle = SubagentHandle(
        run_id="unicode-run",
        label="subagent 🤖 日本語 labels",
        task=task,
        status="done",
        result="Success: 🚀 données sauvegardées with € symbols",
        error="Error with quotes \" ' & ñ",
        spawned_at=10.0,
        completed_at=20.0,
    )
    registry.register(handle)

    file_path = tmp_path / "subagents.json"
    registry.save_state(file_path)

    new_registry = SubagentRegistry()
    loaded = new_registry.load_state(file_path)

    assert "unicode-run" in loaded
    loaded_handle = loaded["unicode-run"]
    assert loaded_handle.label == "subagent 🤖 日本語 labels"
    assert loaded_handle.result == "Success: 🚀 données sauvegardées with € symbols"
    assert loaded_handle.error == "Error with quotes \" ' & ñ"
    assert loaded_handle.status == "orphaned"

    loop.run_until_complete(task)
    loop.close()
