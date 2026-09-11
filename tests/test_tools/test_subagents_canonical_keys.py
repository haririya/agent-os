from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentos.session.keys import canonicalize_session_key
from agentos.session.manager import SessionManager
from agentos.session.models import SessionNode, SessionStatus
from agentos.session.storage import SessionStorage
from agentos.tools.builtin import agents as agents_tool
from agentos.tools.builtin import sessions as sessions_tool
from agentos.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


class _StubSessionManager:
    def __init__(self) -> None:
        self.killed: list[str] = []
        self.injected: list[tuple[str, str]] = []
        self.get_session_calls: list[str] = []
        self.sessions = [
            {
                "session_key": "subagent:agent:main:c1",
                "spawned_by": "agent:main:webchat:default",
                "status": "running",
            },
        ]

    async def get_current_session(self):
        return None

    async def list_sessions(self, spawned_by: str | None = None, **kwargs):
        if spawned_by is not None:
            return [
                s
                for s in self.sessions
                if canonicalize_session_key(s.get("spawned_by"))
                == canonicalize_session_key(spawned_by)
            ]
        return list(self.sessions)

    async def get_session(self, session_key: str):
        self.get_session_calls.append(session_key)
        for s in self.sessions:
            if s["session_key"] == session_key:
                return dict(s)
        return None

    async def kill_session(self, session_key: str) -> None:
        self.killed.append(session_key)

    async def inject_message(self, session_key: str, message: str, provenance: str) -> None:
        self.injected.append((session_key, message))


def _ctx(session_key: str | None) -> ToolContext:
    return ToolContext(
        caller_kind=CallerKind.AGENT,
        session_key=session_key,
        agent_id="main",
    )


@pytest.fixture
def stub_manager():
    mgr = _StubSessionManager()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(None)
    yield mgr
    sessions_tool.set_session_manager(None)
    sessions_tool.set_task_runtime(None)


@pytest.mark.asyncio
async def test_subagents_list_matches_aliased_session_key(
    stub_manager: _StubSessionManager,
) -> None:
    token = current_tool_context.set(_ctx("webchat:default"))
    try:
        raw = await agents_tool.subagents("list")
        payload = json.loads(raw)
    finally:
        current_tool_context.reset(token)

    assert payload["action"] == "list"
    assert len(payload["subagents"]) == 1
    assert payload["subagents"][0]["session_key"] == "subagent:agent:main:c1"


@pytest.mark.asyncio
async def test_subagents_kill_and_steer_accepts_aliased_session_key(
    stub_manager: _StubSessionManager,
) -> None:
    token = current_tool_context.set(_ctx("webchat:default"))
    try:
        # kill
        kill_raw = await agents_tool.subagents("kill", session_key="subagent:agent:main:c1")
        kill_payload = json.loads(kill_raw)
        assert kill_payload["status"] == "killed"
        assert stub_manager.killed == ["subagent:agent:main:c1"]

        # steer
        steer_raw = await agents_tool.subagents(
            "steer", session_key="subagent:agent:main:c1", message="continue"
        )
        steer_payload = json.loads(steer_raw)
        assert steer_payload["status"] == "delivered"
        assert stub_manager.injected == [("subagent:agent:main:c1", "continue")]
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_storage_upsert_canonicalizes_spawned_by_and_parent_session_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    storage = SessionStorage(str(db_path))
    await storage.connect()
    try:
        node = SessionNode(
            session_key="subagent:agent:main:test1",
            session_id="uuid-1",
            agent_id="main",
            parent_session_key="webchat:default",
            spawned_by="webchat:default",
            status=SessionStatus.RUNNING,
        )
        await storage.upsert_session(node)

        # list_sessions queries using canonicalized spawned_by
        results = await storage.list_sessions(spawned_by="webchat:default")
        assert len(results) == 1
        assert results[0].session_key == "subagent:agent:main:test1"
        assert results[0].spawned_by == "agent:main:webchat:default"
        assert results[0].parent_session_key == "agent:main:webchat:default"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_sessions_yield_detects_self_yield_with_alias() -> None:
    class _CurrentSessionManager:
        async def get_current_session(self):
            return type("Obj", (), {"session_key": "agent:main:webchat:default"})()

    sessions_tool.set_session_manager(_CurrentSessionManager())
    try:
        with pytest.raises(ToolError, match="Cannot yield to own session"):
            await sessions_tool.sessions_yield(session_key="webchat:default")
    finally:
        sessions_tool.set_session_manager(None)


@pytest.mark.asyncio
async def test_manager_create_canonicalizes_spawned_by_and_parent(tmp_path: Path) -> None:
    db_path = tmp_path / "manager_test.db"
    storage = SessionStorage(str(db_path))
    await storage.connect()
    try:
        mgr = SessionManager(storage)
        node = await mgr.create(
            session_key="subagent:agent:main:test2",
            spawned_by="webchat:default",
            parent_session_key="webchat:default",
        )
        assert node.spawned_by == "agent:main:webchat:default"
        assert node.parent_session_key == "agent:main:webchat:default"

        # Lookup in storage
        queried = await storage.list_sessions(spawned_by="webchat:default")
        assert len(queried) == 1
        assert queried[0].session_key == "subagent:agent:main:test2"
    finally:
        await storage.close()
